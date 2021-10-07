from json.decoder import JSONDecodeError
from aiohttp import web
import json
import hmac
import hashlib
import aiofiles

class RecieverWebServer():
    def __init__(self, bot):
        self.bot = bot
        self.port = 18271
        self.web_server = web.Application()
        self.web_server.add_routes([web.route('*', '/{callback_type}/{channel}', self._reciever)])

    async def start(self):
        runner = web.AppRunner(self.web_server)
        await runner.setup()
        await web.TCPSite(runner, host="localhost", port=self.port).start()
        self.bot.log.info(f"Webserver running on localhost:{self.port}")
        return self.web_server

    async def _reciever(self, request):
        await self.bot.wait_until_ready()
        channel = request.match_info["channel"]
        callback_type = request.match_info["callback_type"]
        self.bot.log.info(f"{request.method} from {channel}")
        if request.method == 'POST':
            return await self.post_request(request, callback_type, channel)
        return web.Response(status=404)

    async def verify_request(self, request, secret):
        try:
            async with aiofiles.open("cache/notifcache.cache") as f:
                notifcache = json.loads(await f.read())
        except FileNotFoundError:
            notifcache = []
        except json.decoder.JSONDecodeError:
            notifcache = []

        try:
            message_id = request.headers["Twitch-Eventsub-Message-Id"]
            timestamp = request.headers["Twitch-Eventsub-Message-Timestamp"]
            signature = request.headers['Twitch-Eventsub-Message-Signature']
        except KeyError as e:
            self.bot.log.info(f"Request Denied. Missing Key {e}")
            return False
        if message_id in notifcache:
            return None

        hmac_message = message_id.encode("utf-8") + timestamp.encode("utf-8") + await request.read()
        h = hmac.new(secret.encode("utf-8"), hmac_message, hashlib.sha256)
        expected_signature = f"sha256={h.hexdigest()}"
        self.bot.log.debug(f"Timestamp: {timestamp}")
        self.bot.log.debug(f"Expected: {expected_signature}. Receieved: {signature}")
        if signature != expected_signature:
            return False
        notifcache.append(message_id)
        if len(notifcache) > 10: notifcache = notifcache[1:]
        async with aiofiles.open("cache/notifcache.cache", "w") as f:
            await f.write(json.dumps(notifcache, indent=4))
        return True
            

    async def post_request(self, request, callback_type, channel):
        try:
            if callback_type == "titlecallback":
                async with aiofiles.open("config/title_callbacks.json") as f:
                    callbacks = json.loads(await f.read())
            else:
                async with aiofiles.open("config/callbacks.json") as f:
                    callbacks = json.loads(await f.read())
        except FileNotFoundError:
            self.bot.log.error("Failed to read title callbacks config file!")
            return
        except JSONDecodeError:
            self.bot.log.error("Failed to read title callbacks config file!")
            return
        if channel not in callbacks.keys():
            self.bot.log.info(f"Request for {channel} not found")
            return web.Response(status=404)

        verified = await self.verify_request(request, callbacks[channel]["secret"])
        if verified == False:
            self.bot.log.info("Unverified request, aborting")
            return web.Response(status=400)
        elif verified == None:
            self.bot.log.info("Already sent code, ignoring")
            return web.Response(status=202)
        try:
            mode = request.headers["Twitch-Eventsub-Message-Type"]
        except KeyError:
            self.bot.log.info("Missing required parameters")
            return web.Response(status=400)
        data = await request.json()
        
        if mode == "webhook_callback_verification": #Initial Verification of Subscription
            if callback_type == "titlecallback":
                self.bot.log.info(f"Title Change Subscription confirmed for {channel}")
            else:
                self.bot.log.info(f"Subscription confirmed for {channel}")
            challenge = data['challenge']
            return web.Response(status=202, text=challenge)
        elif mode == "authorization_revoked":
            if callback_type == "titlecallback":
                self.bot.log.critical(f"Title Change Authorization Revoked for {channel}!")
            else:
                self.bot.log.critical(f"Authorization Revoked for {channel}!")
            return web.Response(status=202)
        elif mode == "notification":
            if callback_type == "titlecallback":
                self.bot.log.info(f"Title Change Notification for {channel}")
                return await self.title_notification(channel, data)
            else:
                self.bot.log.info(f"Notification for {channel}")
                return await self.notification(channel, data)
        else:
            self.bot.loog.info("Unknown mode")
        return web.Response(status=404)

    async def title_notification(self, channel, data):
        stream = await self.bot.api.get_stream(channel)
        if stream == None:
            live = False
        else:
            live = True
        if not live:
            await self.bot.title_change(channel, data)
        else:
            self.bot.log.info(f"{channel} is live, ignoring title change")

        return web.Response(status=202)

    async def notification(self, channel, data):
        channel = data.get("broadcaster_user_login", channel)
        live = True if data["subscription"]["type"] == "stream.online" else False

        if live:
            notif_info = await self.bot.api.get_stream(channel)
            if notif_info["game_name"] == "":
                notif_info["game_name"] = "<no game>"
            await self.bot.streamer_online(channel, notif_info)
        else:
            await self.bot.streamer_offline(channel)

        return web.Response(status=202)
