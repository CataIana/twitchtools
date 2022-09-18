from __future__ import annotations

import hashlib
import hmac
from typing import TYPE_CHECKING

from aiohttp import web

from twitchtools import PartialYoutubeUser
from twitchtools.enums import AlertOrigin

if TYPE_CHECKING:
    from main import TwitchCallBackBot


class RecieverWebServer:
    def __init__(self, bot, port: int = 18271):
        self.bot: TwitchCallBackBot = bot
        self.port = port
        self.web_server = web.Application()
        self.web_server.add_routes(
            [web.route('*', '/{callback_type}/{channel}', self._reciever)])

        # TO BE USED ONLY FOR DEBUGGING PURPOSES
        self.allow_unverified_requests: bool = False

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
        elif request.method == "GET":
            return await self.get_request(request, callback_type, channel)
        return web.Response(status=404)

    async def verify_request(self, request: web.Request, secret: str):
        if self.allow_unverified_requests:
            return True
        # notif_cache = await get_notif_cache()
        await self.bot.wait_until_db_ready()
        notif_cache = await self.bot.db.get_notif_cache()

        try:
            message_id = request.headers["Twitch-Eventsub-Message-Id"]
            timestamp = request.headers["Twitch-Eventsub-Message-Timestamp"]
            signature = request.headers['Twitch-Eventsub-Message-Signature']
        except KeyError as e:
            self.bot.log.info(f"Twitch request Denied. Missing Key {e}")
            return False
        if message_id in notif_cache:
            return None

        hmac_message = message_id.encode("utf-8") + timestamp.encode("utf-8") + await request.read()
        h = hmac.new(secret.encode("utf-8"), hmac_message, hashlib.sha256)
        expected_signature = f"sha256={h.hexdigest()}"
        self.bot.log.debug(f"Timestamp: {timestamp}")
        self.bot.log.debug(
            f"Expected: {expected_signature}. Receieved: {signature}")
        if signature != expected_signature:
            return False
        notif_cache.append(message_id)
        # await write_notif_cache(notif_cache)
        await self.bot.db.write_notif_cache(notif_cache)
        return True

    async def get_request(self, request: web.Request, callback_type: str, channel: str):
        if callback_type == "youtube":
            try:
                mode = request.query['hub.mode']
                challenge = request.query['hub.challenge']
            except KeyError:
                return web.Response(status=404)
            if mode == "unsubscribe":
                self.bot.log.info(
                    f"Youtube subscription removal confirmed for {channel}")
                return web.Response(text=challenge)
            user = PartialYoutubeUser(channel, "")
            callback = await self.bot.db.get_yt_callback(user)
            if callback is None:
                self.bot.log.info(f"Youtube request for {channel} not found")
                return web.Response(status=404)

            try:
                #mode = request.query['hub.mode']
                #challenge = request.query['hub.challenge']
                verification = request.query['hub.verify_token']
                secret = verification.split(":")[0]
                verify_token = verification.split(":")[-1]
            except KeyError as e:
                self.bot.log.warning(
                    f"Youtube subscription failed: Not all arguments provided {e}")
                return web.Response(status=404)

            if mode == "subscribe" and secret == callback["secret"]:
                self.bot.dispatch(
                    "youtube_subscription_confirmation", verify_token)
                self.bot.log.info(
                    f"Youtube subscription confirmed for {callback['display_name']}")
                return web.Response(text=challenge)
        return web.Response(status=404)

    async def post_request(self, request: web.Request, callback_type: str, channel: str):
        if channel == "_callbacktest":
            return web.Response(status=204)
        if callback_type == "youtube":
            user = PartialYoutubeUser(channel, "")
            callback = await self.bot.db.get_yt_callback(user)
            if callback is None:
                self.bot.log.info(f"Youtube request for {channel} not found")
                return web.Response(status=404)
            data = (await request.read()).decode('utf-8')
            return await self.youtube_notification(PartialYoutubeUser(channel, callback["display_name"]), data)
        else:
            callbacks = await self.bot.db.get_all_callbacks()
            try:
                channel_id = [id for id, c in callbacks.items(
                ) if c["display_name"].lower() == channel][0]
            except IndexError:
                self.bot.log.info(f"Request for {channel} not found")
                return web.Response(status=400)

            verified = await self.verify_request(request, callbacks[channel_id]["secret"])
            if verified == False:
                self.bot.log.info("Unverified request, aborting")
                return web.Response(status=400)
            elif verified == None:
                self.bot.log.info("Request duplicate, ignoring")
                return web.Response(status=202)
            try:
                mode = request.headers["Twitch-Eventsub-Message-Type"]
            except KeyError:
                self.bot.log.info("Missing required parameters")
                return web.Response(status=400)
            data = await request.json()

            if mode == "webhook_callback_verification":  # Initial Verification of Subscription
                if callback_type == "titlecallback":
                    self.bot.dispatch("subscription_confirmation",
                                      data["subscription"]["id"])
                    self.bot.log.info(
                        f"Title Change Subscription confirmed for {channel}")
                else:
                    self.bot.dispatch("subscription_confirmation",
                                      data["subscription"]["id"])
                    self.bot.log.info(f"Subscription confirmed for {channel}")
                challenge = data['challenge']
                return web.Response(status=202, text=challenge)
            elif mode == "authorization_revoked":
                if callback_type == "titlecallback":
                    self.bot.log.critical(
                        f"Title Change Authorization Revoked for {channel}!")
                else:
                    self.bot.log.critical(
                        f"Authorization Revoked for {channel}!")
                return web.Response(status=202)
            elif mode == "notification":
                if callback_type == "titlecallback":
                    # self.bot.log.info(
                    #     f"Title Change Notification for {channel}")
                    return await self.title_notification(channel, data)
                else:
                    # self.bot.log.info(f"Notification for {channel}")
                    return await self.notification(channel, data)
            else:
                self.bot.log.info("Unknown mode")
        return web.Response(status=404)

    async def title_notification(self, channel: str, data: dict):
        event = self.bot.tapi.get_event(data)
        self.bot.queue.put_nowait(event)

        return web.Response(status=202)

    async def notification(self, channel: str, data: dict):
        channel = data["event"].get("broadcaster_user_login", channel)
        streamer = await self.bot.tapi.get_user(user_login=channel)
        stream = await self.bot.tapi.get_stream(streamer, origin=AlertOrigin.callback)

        live = stream is not None
        if self.allow_unverified_requests:
            live = True if data["subscription"]["type"] == "stream.online" else False

        if live:
            self.bot.queue.put_nowait(stream)
        else:
            self.bot.queue.put_nowait(streamer)

        return web.Response(status=202)

    async def youtube_notification(self, channel: PartialYoutubeUser, data: str):
        video = await self.bot.yapi.parse_video_xml(channel, data)

        if video:
            self.bot.queue.put_nowait(video)
        else:
            self.bot.queue.put_nowait(channel)

        return web.Response(status=202)
