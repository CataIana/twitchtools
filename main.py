from __future__ import annotations

import json
import logging
import sys
from asyncio import Event, Queue
from random import choice
from string import ascii_letters
from time import time
from typing import Any, Type, TypeVar, Union

import disnake
from aiohttp import ClientSession
from disnake.ext import commands

from cogs.database import DB
from cogs.webserver import RecieverWebServer
from twitchtools import (BadAuthorization, CustomConnectionState, Emotes,
                         PartialUser, PartialYoutubeUser, Ratelimit,
                         http_twitch, http_youtube)

ACXT = TypeVar(
    "ACXT", bound="disnake.interactions.ApplicationCommandInteraction")


class TwitchCallBackBot(commands.InteractionBot):
    from twitchtools import _sync_application_commands

    def __init__(self):
        intents = disnake.Intents.none()
        intents.guilds = True
        sync_flags = commands.CommandSyncFlags.default()
        sync_flags.sync_commands_debug = True
        super().__init__(intents=intents, command_sync_flags=sync_flags, activity=disnake.Activity(
            type=disnake.ActivityType.listening, name="stream status"))
        self.queue = Queue(maxsize=0)

        self.log: logging.Logger = logging.getLogger("TwitchTools")
        self.log.setLevel(logging.INFO)

        shandler = logging.StreamHandler(sys.stdout)
        shandler.setLevel(self.log.level)
        shandler.setFormatter(logging.Formatter(
            '%(funcName)-26s || %(levelname)-8s || %(message)s'))
        self.log.addHandler(shandler)

        try:
            with open("config/auth.json") as f:
                config = json.load(f)
        except FileNotFoundError:
            raise BadAuthorization
        except json.decoder.JSONDecodeError:
            raise BadAuthorization

        self.web_server = RecieverWebServer(
            self, port=config["webserver_port"])

        self.db_connect_uri = config["mongodb_uri"]
        self._db_ready: Event = Event()
        self.db: DB

        # Mongo DB
        self.load_extension("cogs.database")
        # Functions for events
        self.load_extension("cogs.state_manager")
        # Receives and propogates events
        self.load_extension("cogs.queue_handler")
        # General commands cog
        self.load_extension("cogs.commands")
        # Catches and handles exceptions
        self.load_extension("cogs.error_listener")
        # Cleans up database on being removed from servers
        self.load_extension("cogs.guild_remove_cleanup")
        # Handles catching up state when events may not occur or are missed
        self.load_extension("cogs.catchup")
        # Resubscribes expired channel subscriptions
        self.load_extension("cogs.yt_subscription_handler")
        # Just garbage, maybe I will fix this one day
        self.load_extension("cogs.emotes_sync")

        self.tapi = http_twitch(self, **config)
        self.yapi = http_youtube(self, **config)
        self.token = config["bot_token"]
        self.colour = disnake.Colour.from_rgb(128, 0, 128)
        self.emotes = Emotes
        self._uptime = time()
        self.application_invoke = self.process_application_commands
        self.ratelimits: dict[str, Ratelimit] = {}

    async def ratelimit_request(self, streamer: Union[PartialYoutubeUser, PartialUser]):
        if self.ratelimits.get(streamer.id, None) is None:
            self.ratelimits[streamer.id] = Ratelimit(
                calls=10, period=600, display_name=streamer.display_name)
        self.ratelimits[streamer.id].request()

    async def wait_until_db_ready(self):
        if not self._db_ready.is_set():
            # Want to avoid waiting where possible
            self.log.warning("Waiting for DB")
        await self._db_ready.wait()

    async def close(self):
        if not self.aSession.closed:
            await self.aSession.close()
        await self.tapi.close_session()
        await self.yapi.close_session()
        self.log.info("Shutting down...")
        await super().close()

    @commands.Cog.listener()
    async def on_connect(self):
        self.aSession: ClientSession = ClientSession()  # Make the aiohttp session asap
        await self.web_server.start()

    @commands.Cog.listener()
    async def on_ready(self):
        self.log.info(
            f"------ Logged in as {self.user.name} - {self.user.id} ------")

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

    async def get_slash_context(self, interaction: disnake.interactions.Interaction, *, cls: Type[ACXT] = disnake.interactions.ApplicationCommandInteraction):
        return cls(data=interaction, state=self._connection)

    def random_string_generator(self, str_size=21):
        return "".join(choice(ascii_letters) for _ in range(str_size))


if __name__ == "__main__":
    bot = TwitchCallBackBot()
    bot.run(bot.token)
