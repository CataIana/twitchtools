from __future__ import annotations
from typing import TYPE_CHECKING
from json.decoder import JSONDecodeError
from aiohttp import web
import hmac
import hashlib
if TYPE_CHECKING:
    from main import TwitchCallBackBot

class RecieverWebServer():
    from twitchtools.files import get_notif_cache, write_notif_cache, get_callbacks, get_title_callbacks
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        self.port = 18271
        self.web_server = web.Application()
        self.web_server.add_routes([web.route('*', '/{callback_type}/{channel}', self._reciever)])

    async def start(self):
        runner = web.AppRunner(self.web_server)
        await runner.setup()
        await web.TCPSite(runner, host="localhost", port=self.port).start()
        self.bot.log.info(f"Webserver running on localhost:{self.port}")
        return self.web_server

    async def _reciever(self, request: web.Request):
        await self.bot.wait_until_ready()
        channel = request.match_info["channel"]
        callback_type = request.match_info["callback_type"]
        self.bot.log.info(f"{request.method} from {channel}")
        if request.method == 'POST':
            return await self.post_request(request, callback_type, channel)
        return web.Response(status=404)

    async def verify_request(self, request: web.Request, secret: str):
        if not getattr(self.bot, "notif_cache", None):
            self.bot.notif_cache = await self.get_notif_cache()

        try:
            message_id = request.headers["Twitch-Eventsub-Message-Id"]
            timestamp = request.headers["Twitch-Eventsub-Message-Timestamp"]
            signature = request.headers['Twitch-Eventsub-Message-Signature']
        except KeyError as e:
            self.bot.log.info(f"Request Denied. Missing Key {e}")
            return False
        if message_id in self.bot.notif_cache:
            return None

        hmac_message = message_id.encode("utf-8") + timestamp.encode("utf-8") + await request.read()
        h = hmac.new(secret.encode("utf-8"), hmac_message, hashlib.sha256)
        expected_signature = f"sha256={h.hexdigest()}"
        self.bot.log.debug(f"Timestamp: {timestamp}")
        self.bot.log.debug(f"Expected: {expected_signature}. Receieved: {signature}")
        if signature != expected_signature:
            return False
        self.bot.notif_cache.append(message_id)
        if len(self.bot.notif_cache) > 10: notifcache = self.bot.notif_cache[1:]
        await self.write_notif_cache(self.bot.notif_cache)
        return True
            

    async def post_request(self, request: web.Request, callback_type: str, channel: str):
        try:
            if callback_type == "titlecallback":
                if not getattr(self.bot, "title_callbacks", None):
                    self.bot.title_callbacks = await self.get_title_callbacks()
                callbacks = self.bot.title_callbacks
            else:
                if not getattr(self.bot, "callbacks", None):
                    self.bot.callbacks = await self.get_callbacks()
                callbacks = self.bot.callbacks
        except FileNotFoundError:
            self.bot.log.error("Failed to read title callbacks config file!")
            return
        except JSONDecodeError:
            self.bot.log.error("Failed to read title callbacks config file!")
            return
        if channel not in callbacks.keys():
            self.bot.log.info(f"Request for {channel} not found")
            return web.Response(status=400)

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
                self.bot.dispatch("subscription_confirmation", data["subscription"]["id"])
                self.bot.log.info(f"Title Change Subscription confirmed for {channel}")
            else:
                self.bot.dispatch("subscription_confirmation", data["subscription"]["id"])
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
            self.bot.log.info("Unknown mode")
        return web.Response(status=404)

    async def title_notification(self, channel, data):
        event = self.bot.api.get_event(data)
        self.bot.dispatch("title_change", event)

        return web.Response(status=202)

    async def notification(self, channel, data):
        channel = data.get("broadcaster_user_login", channel)
        streamer = await self.bot.api.get_user(user_login=channel)
        stream = await self.bot.api.get_stream(streamer)

        live = stream is not None

        if live:
            self.bot.dispatch("streamer_online", stream)
        else:
            self.bot.dispatch("streamer_offline", streamer)

        return web.Response(status=202)
