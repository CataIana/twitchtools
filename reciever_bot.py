from discord import Intents, Colour, Embed, PermissionOverwrite, NotFound, Webhook, Forbidden, Activity, ActivityType
from aiohttp import ClientSession
from discord.ext import commands
from systemd.daemon import notify, Notification
from aiohttp import ClientSession
import json
from datetime import datetime
from dateutil.tz import tzlocal
from systemd.journal import JournaldLogHandler
import logging
from time import time
import aiofiles
from reciever_bot_webserver import RecieverWebServer



class TwitchCallBackBot(commands.Bot):
    def __init__(self):
        intents = Intents.none()
        intents.guilds = True
        intents.messages = True
        super().__init__(command_prefix=commands.when_mentioned_or("t!"), case_insensitive=True, intents=intents)

        self.log = logging.getLogger("TwitchTools")
        self.log.setLevel(logging.INFO)

        fhandler = logging.FileHandler(filename="twitchcallbacks.log", encoding="utf-8", mode="a+")
        fhandler.setLevel(logging.INFO)
        fhandler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
        self.log.addHandler(fhandler)

        jhandler = JournaldLogHandler()
        jhandler.setLevel(logging.INFO)
        jhandler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
        self.log.addHandler(jhandler)


        self.web_server = RecieverWebServer(self)
        self.loop.run_until_complete(self.web_server.start())
        
        self.load_extension(f"reciever_bot_cogs")
        self.load_extension(f"emotes_sync")
        self.load_extension(f"error_listener")
        self.colour = Colour.from_rgb(128, 0, 128)
        with open("auth.json") as f:
            self.auth = json.load(f)
        self.token = self.auth["bot_token"]
        self._uptime = time()
        self.aSession = None

    async def close(self):
        notify(Notification.STOPPING)
        await self.aSession.close()
        self.log.info("Shutting down...")
        await super().close()

    @commands.Cog.listener()
    async def on_connect(self):
        self.aSession = ClientSession() #Make the aiohttp session asap

    @commands.Cog.listener()
    async def on_ready(self):
        #await self.catchup_streamers()
        self.log.info(f"------ Logged in as {self.user.name} - {self.user.id} ------")
        await self.change_presence(activity=Activity(type=ActivityType.listening, name="stream status"))
        notify(Notification.READY)

    async def on_message(self, message): return

    async def api_request(self, url, session=None, method="get", **kwargs):
        session = session or self.aSession
        if method == "get":
            response = await session.get(url=url, headers={"Authorization": f"Bearer {self.auth['oauth']}", "Client-Id": self.auth["client_id"]}, **kwargs)
        elif method == "post":
            response = await session.post(url=url, headers={"Authorization": f"Bearer {self.auth['oauth']}", "Client-Id": self.auth["client_id"]}, **kwargs)
        elif method == "delete":
            response = await session.delete(url=url, headers={"Authorization": f"Bearer {self.auth['oauth']}", "Client-Id": self.auth["client_id"]}, **kwargs)
        else:
            return None
        if response.status == 401: #Reauth pog
            reauth = await session.post(url=f"https://id.twitch.tv/oauth2/token?client_id={self.auth['client_id']}&client_secret={self.auth['client_secret']}&grant_type=client_credentials")
            if reauth.status == 401:
                self.bot.log.critical("Well somethin fucked up. Check your credentials!")
                await self.close()
            reauth_data = await reauth.json()
            self.auth["oauth"] = reauth_data["access_token"]
            async with aiofiles.open("auth.json", "w") as f:
                await f.write(json.dumps(self.auth, indent=4))
            if method == "get":
                response = await session.get(url=url, headers={"Authorization": f"Bearer {self.auth['oauth']}", "Client-Id": self.auth["client_id"]}, **kwargs)
            elif method == "post":
                response = await session.post(url=url, headers={"Authorization": f"Bearer {self.auth['oauth']}", "Client-Id": self.auth["client_id"]}, **kwargs)
            elif method == "delete":
                response = await session.delete(url=url, headers={"Authorization": f"Bearer {self.auth['oauth']}", "Client-Id": self.auth["client_id"]}, **kwargs)
            else:
                return None
        else:
            return response

    async def catchup_streamers(self):
        await self.wait_until_ready()
        async with aiofiles.open("callbacks.json") as f:
            callback_info = json.loads(await f.read())
        chunks = [list(callback_info.keys())[x:x+100] for x in range(0, len(list(callback_info.keys())), 100)]
        online_streams = []
        for chunk in chunks:
            response = await self.api_request(f"https://api.twitch.tv/helix/streams?user_login={'&user_login='.join(chunk)}")
            response = await response.json()
            if response.get("error", None) is not None:
                self.log.critical("Invalid oauth token!")
            online_streams += [stream["user_login"] for stream in response["data"]]
        for streamer in callback_info.keys():
            if streamer not in online_streams:
                await self.streamer_offline(streamer)
            else:
                await self.streamer_online(streamer, [x for x in response["data"] if x["user_login"] == streamer][0])


    async def streamer_offline(self, streamer):
        try:
            async with aiofiles.open("channelcache.cache") as f:
                channel_cache = json.loads(await f.read())
        except FileNotFoundError:
            channel_cache = {}
        except json.decoder.JSONDecodeError:
            channel_cache = {}
        async with aiofiles.open("callbacks.json") as f:
            callback_info = json.loads(await f.read())
        if streamer in channel_cache.keys():
            if channel_cache[streamer].get("live_channels", None) is None or channel_cache[streamer].get("live_alerts", None) is None:
                return
            self.log.info(f"Updating status to offline for {streamer}")
            for channel_id in channel_cache[streamer].get("live_channels", []):
                channel = self.get_channel(channel_id)
                if channel is not None:
                    if callback_info[streamer]["alert_roles"][str(channel.guild.id)]["mode"] == 0:
                        await channel.delete()
                    elif callback_info[streamer]["alert_roles"][str(channel.guild.id)]["mode"] == 2:
                        await channel.edit(name="stream-offline")
            if channel_cache[streamer].get("live_channels", None) is not None:
                del channel_cache[streamer]["live_channels"]
            for alert_ids in channel_cache[streamer].get("live_alerts", []):
                channel = self.get_channel(alert_ids["channel"])
                if channel is not None:
                    try:
                        message = await channel.fetch_message(alert_ids["message"])
                    except NotFound:
                        pass
                    else:
                        try:
                            embed = message.embeds[0]
                        except IndexError:
                            pass
                        else:
                            try:
                                embed.set_author(name=embed.author.name.replace("is now live on Twitch!", "was live on Twitch!"), url=embed.author.url)
                                embed.description = f"was playing {embed.description.split('Playing ', 1)[1].split(' for', 1)[0]}"
                                await message.edit(content=message.content.replace("is live on Twitch!", "was live on Twitch!"), embed=embed)
                            except IndexError:
                                self.log.warning(f"Error editing message to offline in {channel.guild.name}")
            if channel_cache[streamer].get("live_alerts", None) is not None:
                del channel_cache[streamer]["live_alerts"]
            async with aiofiles.open("channelcache.cache", "w") as f:
                await f.write(json.dumps(channel_cache, indent=4))

    async def streamer_online(self, streamer, stream_info):
        try:
            async with aiofiles.open("channelcache.cache") as f:
                channel_cache = json.loads(await f.read())
        except FileNotFoundError:
            channel_cache = {}
        except json.decoder.JSONDecodeError:
            channel_cache = {}
        async with aiofiles.open("callbacks.json") as f:
            callback_info = json.loads(await f.read())
        async with aiofiles.open("alert_channels.json") as f:
            alert_channels = json.loads(await f.read())
        only_channel = False
        if int(time()) - channel_cache.get(streamer, {}).get("alert_cooldown", 0) < 600:
            only_channel = True
        #if list(channel_cache.get(streamer, {"alert_cooldown": 0}).keys()) != ["alert_cooldown"]:
        #    self.log.info(f"Ignoring alert while live for {streamer}")
        #    return
        temp = dict(channel_cache.get(streamer, {"alert_cooldown": 0}))
        del temp["alert_cooldown"]
        if list(temp.keys()) != []:
            self.log.info(f"Ignoring alert while live for {streamer}")
            return
        if only_channel:
            self.log.info(f"Cooldown active, not sending alert for {streamer} but creating channels")
        self.log.info(f"Updating status to online for {streamer}")
        #Sending webhook if applicable
        if "webhook" in callback_info[streamer].keys():
            if "format" in callback_info[streamer].keys():
                format_ = callback_info[streamer]["format"].format(**stream_info).replace("\\n", "\n")
            else:
                format_ = "{user_name} is live! Playing {game_name}!\nhttps://twitch.tv/{user_name}".format(**stream_info)
            if type(callback_info[streamer]["webhook"]) == list:
                for webhook in callback_info[streamer]["webhook"]:
                    webhook_obj = Webhook.from_url(webhook, self.aSession)
                    try:
                        await webhook_obj.send(content=format_)
                    except NotFound:
                        pass
            else:
                webhook = Webhook.from_url(callback_info[streamer]["webhook"], self.aSession)
                try:
                    await webhook.send(content=format_)
                except NotFound:
                    pass
        #Send live alert message
        stream_start_time = datetime.strptime(stream_info["started_at"], "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=None) + datetime.now(tzlocal()).utcoffset() #Add timedelta for timezone offset
        embed = Embed(
            title=stream_info["title"], url=f"https://twitch.tv/{stream_info['user_login']}",
            description=f"Playing {stream_info['game_name']} for {stream_info['viewer_count']} viewers\n[Watch Stream](https://twitch.tv/{stream_info['user_login']})",
            colour=8465372, timestamp=stream_start_time)
        embed.set_author(name=f"{stream_info['user_name']} is now live on Twitch!", url=f"https://twitch.tv/{stream_info['user_login']}")
        embed.set_footer(text="Mew")
        SelfOverride = PermissionOverwrite()
        SelfOverride.view_channel = True
        SelfOverride.send_messages = True
        DefaultRole = PermissionOverwrite()
        DefaultRole.view_channel = False
        DefaultRole.send_messages = False
        OverrideRole = PermissionOverwrite()
        OverrideRole.view_channel = True
        live_channels = []
        live_alerts = []
        for guild_id, alert_info in callback_info[streamer]["alert_roles"].items():
            guild = self.get_guild(int(guild_id))
            if guild is not None:
                if alert_info["role_id"] == "everyone":
                    role_mention = f" {guild.default_role}"
                elif alert_info["role_id"] == None:
                    role_mention = ""
                else:
                    role = guild.get_role(alert_info["role_id"])
                    role_mention = f" {role.mention}"
                if not only_channel:
                    alert_channel_id = alert_info.get("channel_override", None)
                    if alert_channel_id == None:
                        alert_channel_id = alert_channels.get(guild_id, None)
                    alert_channel = self.get_channel(alert_channel_id)
                    if alert_channel is not None:
                        try:
                            live_alert = await alert_channel.send(f"{stream_info['user_name']} is live on Twitch!{role_mention}", embed=embed)
                            live_alerts.append({"channel": live_alert.channel.id, "message": live_alert.id})
                        except Forbidden:
                            pass
                #Add channel to live alert list
                if alert_info["mode"] == 0:
                    NewChannelOverrides = {self.user: SelfOverride}
                    if alert_info["role_id"] != "everyone":
                        NewChannelOverrides[guild.default_role] = DefaultRole
                    if alert_info["role_id"] is not None and alert_info["role_id"] != "everyone":
                        NewChannelOverrides[role] = OverrideRole

                    if f"🔴{streamer}" not in [channel.name for channel in guild.text_channels]:
                        channel = await guild.create_text_channel(f"🔴{streamer}", overwrites=NewChannelOverrides, position=0)
                        if channel is not None:
                            try:
                                await channel.send(f"{stream_info['user_name']} is live! https://twitch.tv/{stream_info['user_login']}")
                                live_channels.append(channel.id)
                            except Forbidden:
                                self.log.warning(f"Forbidden error updating {streamer} in guild {guild.name}")
                        else:
                            self.log.warning(f"Error fetching channel ID {alert_info['channel_id']} for {streamer}")
                elif alert_info["mode"] == 2:
                    channel = self.get_channel(alert_info["channel_id"])
                    if channel is not None:
                        try:
                            await channel.edit(name="🔴now-live")
                            live_channels.append(channel.id)
                        except Forbidden:
                            self.log.warning(f"Forbidden error updating {streamer} in guild {channel.guild.name}")
                    else:
                        self.log.warning(f"Error fetching channel ID {alert_info['channel_id']} for {streamer}")
        channel_cache[streamer] = {"alert_cooldown": int(time()), "live_channels": live_channels, "live_alerts": live_alerts}
        async with aiofiles.open("channelcache.cache", "w") as f:
            await f.write(json.dumps(channel_cache, indent=4))


bot = TwitchCallBackBot()
bot.run(bot.token)
