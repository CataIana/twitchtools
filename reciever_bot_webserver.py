from aiohttp import web
import json
import hmac
import hashlib
import aiofiles
from time import time

class RecieverWebServer():
    def __init__(self, bot):
        self.bot = bot
        self.port = 18271
        self.web_server = web.Application()
        self.web_server.add_routes([web.route('*', '/callback/{channel}', self._reciever)])

    async def start(self):
        runner = web.AppRunner(self.web_server)
        await runner.setup()
        await web.TCPSite(runner, host="localhost", port=self.port).start()
        self.bot.log.info(f"Webserver running on localhost:{self.port}")
        return self.web_server

    async def _reciever(self, request):
        await self.bot.wait_until_ready()
        channel = request.match_info["channel"]
        self.bot.log.info(f"{request.method} from {channel}")
        if request.method == 'POST':
            return await self.post_request(request, channel)
        return await self.get_request(request, channel)

    async def verify_request(self, request, channel, secret):
        try: #Verify request
            message_id = request.headers["Twitch-Eventsub-Message-Id"]
            try:
                async with aiofiles.open("notifcache.cache") as f:
                    notifcache = json.loads(await f.read())
                    
            except FileNotFoundError:
                notifcache = []
            except json.decoder.JSONDecodeError:
                notifcache = []
            if message_id in notifcache:
                return None
            hmac_message = request.headers["Twitch-Eventsub-Message-Id"].encode("utf-8") + request.headers["Twitch-Eventsub-Message-Timestamp"].encode("utf-8") + await request.read()
            h = hmac.new(secret.encode("utf-8"), hmac_message, hashlib.sha256)
            expected_signature = f"sha256={h.hexdigest()}"
            self.bot.log.info(f"Timestamp: {request.headers['Twitch-Eventsub-Message-Timestamp']}")
            #self.bot.log.info(f"Expected: {expected_signature}. Receieved: {request.headers['Twitch-Eventsub-Message-Signature']}")
            if request.headers['Twitch-Eventsub-Message-Signature'] != expected_signature:
                return web.Response(status=400)
            notifcache.append(message_id)
            if len(notifcache) > 10: notifcache = notifcache[1:]
            async with aiofiles.open("notifcache.cache", "w") as f:
                await f.write(json.dumps(notifcache, indent=4))
            return True
        except KeyError as e:
            self.bot.log.info(f"Request Denied. Missing Key {e}")
            return False

    async def post_request(self, request, channel):
        async with aiofiles.open("callbacks.json") as f:
            callbacks = json.loads(await f.read())
        if channel not in callbacks.keys():
            self.bot.log.info(f"Request for {channel} not found")
            return web.Response(status=404)

        verified = await self.verify_request(request, channel, callbacks[channel]["secret"])
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
            self.bot.log.info(f"Subscription confirmed for {channel}")
            challenge = data['challenge']
            return web.Response(status=202, text=challenge)
        elif mode == "authorization_revoked":
            self.bot.log.critical(f"Authorization Revoked for {channel}!")
        elif mode == "notification":
            self.bot.log.info(f"Notification for {channel}")
            await self.notification(channel, data)
        else:
            self.bot.loog.info("Unknown mode")
        return web.Response(status=404)

    async def notification(self, channel, data):
        channel = data.get("broadcaster_user_login", channel)
        live = True if data["subscription"]["type"] == "stream.online" else False

        if live:
            response = await self.bot.api_request(f"https://api.twitch.tv/helix/streams?user_login={channel}")
            if response.status != 200:
                return self.bot.log.critical(f"Failed to fetch stream info!")
            notif_json = await response.json()
            notif_info = notif_json["data"][0]
            if notif_info["game_name"] == "":
                notif_info["game_name"] = "<no game>"
            await self.bot.streamer_online(channel, notif_info)
        else:
            await self.bot.streamer_offline(channel)

        return web.Response(status=202)