from discord import Intents, Colour, Embed, PermissionOverwrite
from discord.ext import commands
from systemd.daemon import notify, Notification
from requests import Session
from asyncio import sleep
import json
from datetime import datetime
#from time import time
from systemd.journal import JournaldLogHandler
import logging
from reciever_bot_cogs import RecieverCommands
from reciever_bot_webserver import RecieverWebServer


class TwitchCallBackBot(commands.Bot):
    def __init__(self):
        intents = Intents.none()
        intents.guilds = True
        intents.messages = True
        super().__init__(command_prefix="t!", case_insensitive=True, intents=intents, help_command=None)

        self.log = logging.getLogger("TwitchTools")
        self.log.setLevel(logging.DEBUG)

        fhandler = logging.FileHandler(filename="twitchcallbacks.log", encoding="utf-8", mode="a+")
        fhandler.setLevel(logging.INFO)
        fhandler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
        self.log.addHandler(fhandler)

        jhandler = JournaldLogHandler()
        jhandler.setLevel(logging.DEBUG)
        jhandler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
        self.log.addHandler(jhandler)


        self.web_server = RecieverWebServer(self)
        self.loop.run_until_complete(self.web_server.start())
        self.main_guild = 749646865531928628
        self.alert_channel = 769391641109856276
        
        self.add_cog(RecieverCommands(self))
        self.colour = Colour.from_rgb(128, 0, 128)
        self.rSession = Session()
        with open("auth.json") as f:
            auth = json.load(f)
        self.token = auth["bot_token"]

    async def close(self):
        notify(Notification.STOPPING)
        await super().close()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.catchup_streamers()
        self.log.info(f"------ Logged in as {self.user.name} - {self.user.id} ------")
        notify(Notification.READY)

    async def on_message(self, message): return

    async def catchup_streamers(self):
        with open("auth.json") as f:
            auth = json.load(f)
        with open("callbacks.json") as f:
            callback_info = json.load(f)
        for streamer in callback_info.keys():
            await sleep(0.2)
            response = self.rSession.get(url=f"https://api.twitch.tv/helix/streams?user_login={streamer}", headers={"Authorization": f"Bearer {auth['oauth']}", "Client-Id": auth["client_id"]}).json()
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
        if streamer in channel_cache.keys():
            self.log.info(f"Updating status to offline for {streamer}")
            channel = self.get_channel(channel_cache[streamer]["live_channel"])
            if channel is not None:
                await channel.delete()
            channel = self.get_channel(channel_cache[streamer]["live_alert"]["channel"])
            message = await channel.fetch_message(channel_cache[streamer]["live_alert"]["message"])
            embed = message.embeds[0]
            embed.set_author(name=embed.author.name.replace("is now live on Twitch!", "was live on Twitch!"), url=embed.author.url)
            embed.description = f"was playing {embed.description.split('Playing ', 1)[1].split(' for', 1)[0]}"
            await message.edit(content=message.content.replace("is live on Twitch!", "was live on Twitch!"), embed=embed)
            del channel_cache[streamer]
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
        if streamer not in channel_cache.keys():
            self.log.info(f"Updating status to online for {streamer}")
            #Send live alert message
            alert_channel = self.get_channel(self.alert_channel)
            embed = Embed(
                title=stream_info["title"], url=f"https://twitch.tv/{stream_info['user_login']}",
                description=f"Playing {stream_info['game_name']} for {stream_info['viewer_count']} viewers\n[Watch Stream](https://twitch.tv/{stream_info['user_login']})",
                colour=8465372, timestamp=datetime.strptime(stream_info["started_at"], "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=None))
            embed.set_author(name=f"{stream_info['user_name']} is now live on Twitch!", url=f"https://twitch.tv/{stream_info['user_login']}")
            embed.set_footer(text="Mew")
            g = self.get_guild(self.main_guild)
            if "alert_role" in callback_info[streamer]:
                alert_role = g.get_role(callback_info[streamer]['alert_role'])
                live_alert = await alert_channel.send(f"{stream_info['user_name']} is live on Twitch! {alert_role.mention}", embed=embed)
            else:
                live_alert = await alert_channel.send(f"{stream_info['user_name']} is live on Twitch!", embed=embed)
            #Add channel to live alert list
            channel = await g.create_text_channel(f"🔴{streamer}")
            await channel.send(f"{stream_info['user_name']} is live! https://twitch.tv/{stream_info['user_login']}")
            SelfOverride = PermissionOverwrite()
            SelfOverride.view_channel = True
            SelfOverride.send_messages = True
            await channel.set_permissions(self.user, overwrite=SelfOverride)
            DefaultRole = PermissionOverwrite()
            DefaultRole.view_channel = False
            DefaultRole.send_messages = False
            await channel.set_permissions(g.default_role, overwrite=DefaultRole)
            if "alert_role" in callback_info[streamer]:
                OverrideRole = PermissionOverwrite()
                OverrideRole.view_channel = True
                await channel.set_permissions(alert_role, overwrite=OverrideRole)
            await channel.edit(position=0, category=None)
            channel_cache[streamer] = {"live_channel": channel.id, "live_alert": {"channel": live_alert.channel.id, "message": live_alert.id}}
            with open("channelcache.cache", "w") as f:
                f.write(json.dumps(channel_cache, indent=4))
            

bot = TwitchCallBackBot()
bot.run(bot.token)
