from discord import Intents, Colour, Embed, PermissionOverwrite, NotFound, Webhook, AsyncWebhookAdapter, Forbidden, Activity, ActivityType
from aiohttp import ClientSession
from discord.ext import commands, tasks
from systemd.daemon import notify, Notification
from aiohttp import ClientSession
from asyncio import sleep
import json
from datetime import datetime
#from time import time
from systemd.journal import JournaldLogHandler
import logging
from time import time
from reciever_bot_webserver import RecieverWebServer



class TwitchCallBackBot(commands.Bot):
    def __init__(self):
        intents = Intents.none()
        intents.guilds = True
        intents.messages = True
        super().__init__(command_prefix="t!", case_insensitive=True, intents=intents)

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
        
        self.load_extension(f'reciever_bot_cogs')
        self.colour = Colour.from_rgb(128, 0, 128)
        with open("auth.json") as f:
            self.auth = json.load(f)
        self.token = self.auth["bot_token"]
        self._uptime = time()

    async def close(self):
        notify(Notification.STOPPING)
        await self.aSession.close()
        self.log.info("Shutting down...")
        await super().close()

    @commands.Cog.listener()
    async def on_ready(self):
        self.aSession = ClientSession()
        await self.catchup_streamers()
        self.log.info(f"------ Logged in as {self.user.name} - {self.user.id} ------")
        await self.change_presence(activity=Activity(type=ActivityType.listening, name="stream status"))
        notify(Notification.READY)

    async def on_message(self, message): return

    async def catchup_streamers(self):
        with open("callbacks.json") as f:
            callback_info = json.load(f)
        for streamer in callback_info.keys():
            await sleep(0.2)
            response = await (await self.aSession.get(url=f"https://api.twitch.tv/helix/streams?user_login={streamer}", headers={"Authorization": f"Bearer {self.auth['oauth']}", "Client-Id": self.auth["client_id"]})).json()
            if response.get("error", None) is not None:
                self.log.critical("Invalid oauth token!")
                self.log.critical(f"Reauthorize with link: https://id.twitch.tv/oauth2/authorize?client_id={self.auth['client_id']}&redirect_uri=https://twitchapps.com/tmi/&response_type=token")
                exit()
            if response["data"] == []:
                await self.streamer_offline(streamer)
            else:
                await self.streamer_online(streamer, response["data"][0])


    async def streamer_offline(self, streamer):
        try:
            with open("channelcache.cache") as f:
                channel_cache = json.load(f)
        except FileNotFoundError:
            channel_cache = {}
        except json.decoder.JSONDecodeError:
            channel_cache = {}
        with open("callbacks.json") as f:
            callback_info = json.load(f)
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
            with open("channelcache.cache", "w") as f:
                f.write(json.dumps(channel_cache, indent=4))

    async def streamer_online(self, streamer, stream_info):
        try:
            with open("channelcache.cache") as f:
                channel_cache = json.load(f)
        except FileNotFoundError:
            channel_cache = {}
        except json.decoder.JSONDecodeError:
            channel_cache = {}
        with open("callbacks.json") as f:
            callback_info = json.load(f)
        with open("alert_channels.json") as f:
            alert_channels = json.load(f)
        only_channel = False
        if int(time()) - channel_cache.get(streamer, {}).get("alert_cooldown", 0) < 600:
            only_channel = True
        if list(channel_cache.get(streamer, {"alert_cooldown": 0}).keys()) != ["alert_cooldown"]:
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
                    webhook_obj = Webhook.from_url(webhook, adapter=AsyncWebhookAdapter(self.aSession))
                    await webhook_obj.send(content=format_)
            else:
                webhook = Webhook.from_url(callback_info[streamer]["webhook"], adapter=AsyncWebhookAdapter(self.aSession))
                await webhook.send(content=format_)
        #Send live alert message
        embed = Embed(
            title=stream_info["title"], url=f"https://twitch.tv/{stream_info['user_login']}",
            description=f"Playing {stream_info['game_name']} for {stream_info['viewer_count']} viewers\n[Watch Stream](https://twitch.tv/{stream_info['user_login']})",
            colour=8465372, timestamp=datetime.strptime(stream_info["started_at"], "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=None))
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
            if alert_info["role_id"] == "everyone":
                role_mention = f" {guild.default_role}"
            elif alert_info["role_id"] == None:
                role_mention = ""
            else:
                role = guild.get_role(alert_info["role_id"])
                role_mention = f" {role.mention}"
            if not only_channel:
                try:
                    alert_channel = self.get_channel(alert_channels[guild_id])
                    live_alert = await alert_channel.send(f"{stream_info['user_name']} is live on Twitch!{role_mention}", embed=embed)
                    live_alerts.append({"channel": live_alert.channel.id, "message": live_alert.id})
                except KeyError:
                    pass
            #Add channel to live alert list
            if alert_info["mode"] == 0:
                NewChannelOverrides = {self.user: SelfOverride}
                if alert_info["role_id"] != "everyone":
                    NewChannelOverrides[guild.default_role] = DefaultRole
                if alert_info["role_id"] is not None and alert_info["role_id"] != "everyone":
                    NewChannelOverrides[role] = OverrideRole

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
        with open("channelcache.cache", "w") as f:
            f.write(json.dumps(channel_cache, indent=4))


bot = TwitchCallBackBot()
bot.run(bot.token)
