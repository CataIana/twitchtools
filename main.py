from __future__ import annotations
import discord
from dislash import InteractionClient
from discord.ext import commands
from discord.utils import MISSING
from cogs.webserver import RecieverWebServer
from twitchtools.api import http
from aiohttp import ClientSession
from time import time
import logging
import json
import sys

from twitchtools.user import PartialUser

class TwitchCallBackBot(commands.Bot):
    from twitchtools.files import get_callbacks
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(command_prefix=commands.when_mentioned_or("t!"), intents=intents, activity=discord.Activity(type=discord.ActivityType.listening, name="stream status"))

        self.log: logging.Logger = logging.getLogger("TwitchTools")
        self.log.setLevel(logging.INFO)

        shandler = logging.StreamHandler(sys.stdout)
        shandler.setLevel(logging.INFO)
        shandler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
        self.log.addHandler(shandler)

        self.slash: InteractionClient = InteractionClient(self)
        self.api: http = http(self, auth_file=f"config/auth.json")
        self.web_server: RecieverWebServer = RecieverWebServer(self)
        self.loop.run_until_complete(self.web_server.start())

        self.load_extension(f"cogs.reciever_bot_cogs")
        self.load_extension(f"cogs.emotes_sync")
        self.load_extension(f"cogs.error_listener")
        self.load_extension(f"cogs.streamer_status")
        self.colour: discord.Colour = discord.Colour.from_rgb(128, 0, 128)
        with open("config/auth.json") as f:
            self.auth: dict = json.load(f)
        self.token = self.auth["bot_token"]
        self._uptime = time()

        self.callbacks: dict = MISSING
        self.title_callbacks: dict = MISSING
        self.channel_cache: dict = MISSING
        self.title_cache: dict = MISSING
        self.notif_cache: dict = MISSING

    async def close(self):
        await self.aSession.close()
        self.log.info("Shutting down...")
        await super().close()

    @commands.Cog.listener()
    async def on_connect(self):
        self.aSession: ClientSession = ClientSession() #Make the aiohttp session asap

    @commands.Cog.listener()
    async def on_ready(self):
        self.log.info(f"------ Logged in as {self.user.name} - {self.user.id} ------")

    async def catchup_streamers(self):
        await self.wait_until_ready()
        if not getattr(self, "callbacks", None):
            self.callbacks = await self.get_callbacks() #Get callback dict
        if not self.callbacks:
            return
        streams = await self.api.get_streams(user_ids=[c["channel_id"] for c in self.callbacks.values()]) #Fetch all streamers, returning the currently live ones
        online_streams = [stream.user.id for stream in streams] #We only need the ID from them
        for streamer, data in self.callbacks.items(): #Iterate through all callbacks and update all streamers
            if data["channel_id"] in online_streams:
                self.dispatch("streamer_online", [x for x in streams if x.user.id == data["channel_id"]][0])
            else:
                self.dispatch("streamer_offline", PartialUser(user_id=data["channel_id"], user_login=streamer, display_name=streamer))
    

if __name__ == "__main__":
    bot = TwitchCallBackBot()
    bot.run(bot.token)
