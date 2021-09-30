from json.decoder import JSONDecodeError
from discord import Intents, Colour, Embed, PermissionOverwrite, NotFound, Webhook, Forbidden, Activity, ActivityType, HTTPException
from discord.ext import commands
from reciever_bot_webserver import RecieverWebServer
from aiohttp import ClientSession
from datetime import datetime
from dateutil.tz import tzlocal
from systemd.daemon import notify, Notification
from systemd.journal import JournaldLogHandler
from time import time
import aiofiles
import logging
import json
from dislash import InteractionClient



class TwitchCallBackBot(commands.Bot):
    def __init__(self):
        intents = Intents.none()
        intents.guilds = True
        intents.messages = True
        super().__init__(command_prefix=commands.when_mentioned_or("t!"), case_insensitive=True, intents=intents, activity=Activity(type=ActivityType.listening, name="t!help"))

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

        self.slash = InteractionClient(self)
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
        self.log.info(f"------ Logged in as {self.user.name} - {self.user.id} ------")
        notify(Notification.READY)

    async def on_message(self, message): return

    async def api_request(self, url, session=None, method="get", **kwargs):
        session = session or self.aSession
        response = await session.request(method=method, url=url, headers={"Authorization": f"Bearer {self.auth['oauth']}", "Client-Id": self.auth["client_id"]}, **kwargs)
        if response.status == 401: #Reauth pog
            reauth = await session.post(url=f"https://id.twitch.tv/oauth2/token?client_id={self.auth['client_id']}&client_secret={self.auth['client_secret']}&grant_type=client_credentials")
            if reauth.status == 401:
                self.bot.log.critical("Well somethin fucked up. Check your credentials!")
                await self.close()
            reauth_data = await reauth.json()
            self.auth["oauth"] = reauth_data["access_token"]
            async with aiofiles.open("auth.json", "w") as f:
                await f.write(json.dumps(self.auth, indent=4))
            response = await session.request(method=method, url=url, headers={"Authorization": f"Bearer {self.auth['oauth']}", "Client-Id": self.auth["client_id"]}, **kwargs)
        else:
            return response

    async def catchup_streamers(self):
        await self.wait_until_ready()
        try:
            async with aiofiles.open("callbacks.json") as f:
                callbacks = json.loads(await f.read())
        except FileNotFoundError:
            return
        except JSONDecodeError:
            return
        chunks = [[c["channel_id"] for c in callbacks.values()][x:x+100] for x in range(0, len([c["channel_id"] for c in callbacks.values()]), 100)] #Split list of streamers into chunks of 100.
        online_streams = []
        for chunk in chunks: #Fetch chunks and create list of online streams
            response = await self.api_request(f"https://api.twitch.tv/helix/streams?user_id={'&user_id='.join(chunk)}")
            response = await response.json()
            online_streams += [stream["user_id"] for stream in response["data"]]
        for streamer, data in callbacks.items(): #Iterate through all callbacks and run
            if data["channel_id"] not in online_streams:
                await self.streamer_offline(streamer)
            else:
                await self.streamer_online(streamer, [x for x in response["data"] if x["user_id"] == data["channel_id"]][0])

    async def title_change(self, streamer, stream_info):
        try:
            async with aiofiles.open("titlecache.cache") as f:
                title_cache = json.loads(await f.read())
        except FileNotFoundError:
            title_cache = {}
        except json.decoder.JSONDecodeError:
            title_cache = {}
        old_title = title_cache.get(streamer, {}).get("cached_title", "<no title>")
        old_game = title_cache.get(streamer, {}).get("cached_game", "<no game>")
        #Prevent errors with empty content values
        if stream_info["event"]["title"] == "":
            stream_info["event"]["title"] = "<no title>"
        if stream_info["event"]["category_name"] == "":
            stream_info["event"]["category_name"] = "<no game>"

        updated = [] #Quick way to make the dynamic title
        if stream_info["event"]["title"] != old_title:
            updated.append("title")
        if stream_info["event"]["category_name"] != old_game:
            updated.append("game")

        if updated == []: #If for some reason neither the title or game updated, just ignore
            self.log.info(f"No title updates for {streamer}, ignoring")
            return

        title_cache[streamer] = { #Update cached data
            "cached_title": stream_info["event"]["title"],
            "cached_game": stream_info["event"]["category_name"],
        }

        async with aiofiles.open("titlecache.cache", "w") as f:
            await f.write(json.dumps(title_cache, indent=4))

        embed = Embed(description=f"{stream_info['event']['broadcaster_user_name']} updated their {' and '.join(updated)}", colour=0x812BDC, timestamp=datetime.utcnow())
        if stream_info["event"]["title"] != old_title:
            embed.add_field(name="Old Title", value=old_title, inline=True)
            embed.add_field(name="New Title", value=stream_info["event"]["title"], inline=True)
        if stream_info["event"]["category_name"] != old_game:
            embed.add_field(name="Old Game", value=old_game, inline=True)
            embed.add_field(name="New Game", value=stream_info["event"]["category_name"], inline=True)
        embed.set_author(name=f"Stream Link", url=f"https://twitch.tv/{stream_info['event']['broadcaster_user_login']}")
        embed.set_footer(text="Mew")

        async with aiofiles.open("title_callbacks.json") as f:
            callbacks = json.loads(await f.read())

        self.log.info(f"Sending title update for {streamer}")

        for data in callbacks[streamer]["alert_roles"].values():
            c = self.get_channel(data["notif_channel_id"])
            if c is not None:
                if data['role_id'] is None:
                    role_mention = ""
                elif data["role_id"] == "everyone":
                    role_mention = "@everyone"
                else:
                    role_mention = f"<@&{data['role_id']}>"
                try:
                    await c.send(f"{role_mention}", embed=embed)
                except Forbidden:
                    pass
                except HTTPException:
                    pass
            else:
                self.log.warning("Invalid channel")


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
        only_channel = False
        if int(time()) - channel_cache.get(streamer, {}).get("alert_cooldown", 0) < 600:
            only_channel = True
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
                        alert_channel_id = alert_info.get("notif_channel_id", None)
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
