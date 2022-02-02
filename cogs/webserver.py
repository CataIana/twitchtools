from __future__ import annotations
from aiohttp import web
from twitchtools.enums import AlertOrigin
from twitchtools.files import get_notif_cache, write_notif_cache, get_callbacks, get_title_callbacks
from json.decoder import JSONDecodeError
import hmac
import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import TwitchCallBackBot

class RecieverWebServer:
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        self.port = 18271
        self.web_server = web.Application()
        self.web_server.add_routes([web.route('*', '/{callback_type}/{channel}', self._reciever)])

        self.allow_unverified_requests: bool = False # TO BE USED ONLY FOR DEBUGGING PURPOSES

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
        if self.allow_unverified_requests:
            return True
        notif_cache = await get_notif_cache()

        try:
            message_id = request.headers["Twitch-Eventsub-Message-Id"]
            timestamp = request.headers["Twitch-Eventsub-Message-Timestamp"]
            signature = request.headers['Twitch-Eventsub-Message-Signature']
        except KeyError as e:
            self.bot.log.info(f"Request Denied. Missing Key {e}")
            return False
        if message_id in notif_cache:
            return None

        hmac_message = message_id.encode("utf-8") + timestamp.encode("utf-8") + await request.read()
        h = hmac.new(secret.encode("utf-8"), hmac_message, hashlib.sha256)
        expected_signature = f"sha256={h.hexdigest()}"
        self.bot.log.debug(f"Timestamp: {timestamp}")
        self.bot.log.debug(f"Expected: {expected_signature}. Receieved: {signature}")
        if signature != expected_signature:
            return False
        notif_cache.append(message_id)
        await write_notif_cache(notif_cache)
        return True
            

    async def post_request(self, request: web.Request, callback_type: str, channel: str):
        if channel == "_callbacktest":
            return web.Response(status=204)
        try:
            if callback_type == "titlecallback":
                callbacks = await get_title_callbacks()
            else:
                callbacks = await get_callbacks()
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
        self.bot.queue.put_nowait(event)
        #self.bot.dispatch("title_change", event)

        return web.Response(status=202)

    async def notification(self, channel, data):
        channel = data["event"].get("broadcaster_user_login", channel)
        streamer = await self.bot.api.get_user(user_login=channel)
        stream = await self.bot.api.get_stream(streamer, origin=AlertOrigin.callback)

        live = stream is not None

        
        if live:
            #self.bot.dispatch("streamer_online", stream)
            self.bot.queue.put_nowait(stream)
        else:
            #self.bot.dispatch("streamer_offline", streamer)
            self.bot.queue.put_nowait(streamer)

        return web.Response(status=202)
