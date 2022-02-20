from __future__ import annotations
import disnake
from disnake.ext import commands
from asyncio import Queue
from cogs.webserver import RecieverWebServer
from twitchtools.api import http
from aiohttp import ClientSession
from time import time
import logging
import json
import sys
from twitchtools import PartialUser, AlertOrigin, get_callbacks
from twitchtools.connection_state import CustomConnectionState
from typing import TypeVar, Type, Any
from enum import Enum

ACXT = TypeVar("ACXT", bound="disnake.ApplicationCommandInteraction")

class Emotes(Enum):
    error: str = "<:red_tick:809191812337369118>"
    success: str = "<:green_tick:809191812434231316>"

    #Override str conversion to return value so we don't have to add .value to every usage
    def __str__(self):
        #return "%s.%s" % (self.__class__.__name__, self._name_)
        return self._value_

class TwitchCallBackBot(commands.InteractionBot):
    from twitchtools import _sync_application_commands

    def __init__(self):
        intents = disnake.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents, activity=disnake.Activity(type=disnake.ActivityType.listening, name="stream status"))
        self._sync_commands_debug = True

        self.queue = Queue(maxsize=0)

        self.log: logging.Logger = logging.getLogger("TwitchTools")
        self.log.setLevel(logging.INFO)

        shandler = logging.StreamHandler(sys.stdout)
        shandler.setLevel(self.log.level)
        shandler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
        self.log.addHandler(shandler)

        self.api: http = http(self, auth_file=f"config/auth.json")
        self.web_server: RecieverWebServer = RecieverWebServer(self)
        self.loop.run_until_complete(self.web_server.start())

        self.load_extension(f"cogs.reciever_bot_cogs")
        self.load_extension(f"cogs.emotes_sync")
        self.load_extension(f"cogs.error_listener")
        self.load_extension(f"cogs.streamer_status")
        self.load_extension(f"cogs.queue_worker")
        self.load_extension(f"cogs.guild_remove_cleanup")
        self.colour = disnake.Colour.from_rgb(128, 0, 128)
        self.emotes = Emotes
        with open("config/auth.json") as f:
            self.auth: dict = json.load(f)
        self.token = self.auth["bot_token"]
        self._uptime = time()
        self.application_invoke = self.process_application_commands

    async def close(self):
        if not self.aSession.closed:
            await self.aSession.close()
        self.log.info("Shutting down...")
        await super().close()

    @commands.Cog.listener()
    async def on_connect(self):
        self.aSession: ClientSession = ClientSession() #Make the aiohttp session asap

    @commands.Cog.listener()
    async def on_ready(self):
        self.log.info(f"------ Logged in as {self.user.name} - {self.user.id} ------")

    def _get_state(self, **options: Any) -> CustomConnectionState:
        return CustomConnectionState(
            dispatch=self.dispatch,
            handlers=self._handlers,
            hooks=self._hooks,
            http=self.http,
            loop=self.loop,
            **options,
        )

    async def on_application_command(self, interaction): return

    async def get_slash_context(self, interaction: disnake.Interaction, *, cls: Type[ACXT] = disnake.ApplicationCommandInteraction):
        return cls(data=interaction, state=self._connection)

    async def catchup_streamers(self):
        await self.wait_until_ready()
        callbacks = await get_callbacks() #Get callback dict
        if not callbacks:
            return
        streams = await self.api.get_streams(user_ids=[c["channel_id"] for c in callbacks.values()], origin=AlertOrigin.catchup) #Fetch all streamers, returning the currently live ones
        online_streams = [stream.user.id for stream in streams] #We only need the ID from them
        for streamer, data in callbacks.items(): #Iterate through all callbacks and update all streamers
            if data["channel_id"] in online_streams:
                self.queue.put_nowait([x for x in streams if x.user.id == data["channel_id"]][0])
                #self.dispatch("streamer_online", [x for x in streams if x.user.id == data["channel_id"]][0])
            else:
                #self.dispatch("streamer_offline", PartialUser(user_id=data["channel_id"], user_login=streamer, display_name=streamer))
                self.queue.put_nowait(PartialUser(user_id=data["channel_id"], user_login=streamer, display_name=streamer))
    

if __name__ == "__main__":
    bot = TwitchCallBackBot()
    bot.run(bot.token)
