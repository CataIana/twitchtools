from json.decoder import JSONDecodeError
from aiohttp import web
import json

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

    async def get_request(self, request, channel):
        with open("callbacks.json") as f:
            callbacks = json.load(f)
        if channel not in callbacks.keys():
            self.bot.log.info(f"Request for {channel} not found")
            return web.Response(status=404)

        try:
            reason = request.query['hub.reason']
        except KeyError:
            pass
        else:
            self.bot.log.info(f"Subscription Denied. Reason: {reason}")
            return web.Response(status=404)

        try:
            mode = request.query['hub.mode']
            challenge = request.query['hub.challenge']
        except KeyError:
            self.bot.log.warn("Not all arguments provided")
            return web.Response(status=404)

        if mode == "subscribe":
            self.bot.log.info(f"Subscription confirmed for {channel}")
            return web.Response(text=challenge)
        # elif mode == "unsubscribe" and secret == callbacks["channel"]["secret"]:
        #     self.bot.log.info(f"Unsubscription confirmed for {channel}")
        #     return challenge
        return web.Response(status=404)

    async def post_request(self, request, channel):
        with open("callbacks.json") as f:
            callbacks = json.load(f)
        if channel not in callbacks.keys():
            self.bot.log.warning(f"Request for {channel} not found")
            return web.Response(status=404)

        try:
            notification_id = request.headers['Twitch-Notification-Id']
        except KeyError:
            return web.Response(status=404)
        try:
            notif_info = (await request.json())["data"]
        except KeyError:
            return web.Response(status=404)
        except JSONDecodeError:
            return web.Response(status=404)
        self.bot.log.debug(f"Payload: {json.dumps(notif_info, indent=4)}")
        self.bot.log.debug(f"Notification ID: {notification_id}")

        try:
            with open("notifcache.cache") as f:
                notification_cache = json.load(f)
        except FileNotFoundError:
            notification_cache = []
        except json.decoder.JSONDecodeError:
            notification_cache = []

        if notif_info == []:
            live = False
            notif_info = {}
        else:
            live = True
            notif_info = notif_info[0]
        
        if notification_id not in [item[0] for item in notification_cache]:
            duplicate = False
        else:
            for notification in notification_cache:
                if notification[0] == notification_id:
                    old_notification_cache = notification
                    break
            if old_notification_cache[1] == live:
                duplicate = True
            else:
                duplicate = False

        if not duplicate:
            if live:
                if notif_info["game_name"] == "":
                    notif_info["game_name"] = "<no game>"
                await self.bot.streamer_online(channel, notif_info)
            else:
                await self.bot.streamer_offline(channel)

            notification_cache.append([notification_id, live])
            if len(notification_cache) > 10: notification_cache = notification_cache[1:]
            with open("notifcache.cache", "w") as f:
                f.write(json.dumps(notification_cache, indent=4))

        return web.Response(status=202)