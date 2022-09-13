from __future__ import annotations
import disnake
from disnake.ext import commands
from asyncio import Queue, Event
from aiohttp import ClientSession
from twitchtools.api import http
from twitchtools import CustomConnectionState, PartialUser, AlertOrigin, BadAuthorization
from cogs.database import DB
from cogs.webserver import RecieverWebServer
from twitchtools.files import get_callbacks, get_title_callbacks
from time import time
import logging
import json
import sys
from typing import TypeVar, Type, Any
from enum import Enum

ACXT = TypeVar("ACXT", bound="disnake.ApplicationCommandInteraction")


class Emotes(Enum):
    error: str = "❌"
    success: str = "✅"

    # Override str conversion to return value so we don't have to add .value to every usage
    def __str__(self):
        # return "%s.%s" % (self.__class__.__name__, self._name_)
        return self._value_


class TwitchCallBackBot(commands.InteractionBot):
    from twitchtools import _sync_application_commands

    def __init__(self):
        intents = disnake.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents, activity=disnake.Activity(
            type=disnake.ActivityType.listening, name="stream status"))
        self._sync_commands_debug = True
        self.queue = Queue(maxsize=0)

        self.log: logging.Logger = logging.getLogger("TwitchTools")
        self.log.setLevel(logging.INFO)

        shandler = logging.StreamHandler(sys.stdout)
        shandler.setLevel(self.log.level)
        shandler.setFormatter(logging.Formatter(
            '%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
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
        self.loop.run_until_complete(self.web_server.start())

        self.db_connect_uri = config["mongodb_uri"]
        self._db_ready: Event = Event()
        self.db: DB

        self.load_extension("cogs.database")
        self.load_extension("cogs.streamer_status")
        self.load_extension("cogs.queue_handler")
        self.load_extension("cogs.reciever_bot_cogs")
        self.load_extension("cogs.error_listener")
        self.load_extension("cogs.guild_remove_cleanup")
        self.load_extension("cogs.emotes_sync")

        self.api: http = http(self, **config)
        self.token = config["bot_token"]
        self.colour = disnake.Colour.from_rgb(128, 0, 128)
        self.emotes = Emotes
        self._uptime = time()
        self.application_invoke = self.process_application_commands

    async def wait_until_db_ready(self):
        if not self._db_ready.is_set():
            # Want to avoid waiting where possible
            self.log.warning("Waiting for DB")
        await self._db_ready.wait()

    async def close(self):
        if not self.aSession.closed:
            await self.aSession.close()
        self.log.info("Shutting down...")
        await super().close()

    @commands.Cog.listener()
    async def on_connect(self):
        self.aSession: ClientSession = ClientSession()  # Make the aiohttp session asap

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

    async def get_slash_context(self, interaction: disnake.Interaction, *, cls: Type[ACXT] = disnake.ApplicationCommandInteraction):
        return cls(data=interaction, state=self._connection)

    async def catchup_streamers(self):
        await self.wait_until_ready()
        await self.wait_until_db_ready()
        callbacks = await self.db.get_all_callbacks()
        if callbacks == {}:
            return

        # Fetch all streamers, returning the currently live ones
        streams = await self.api.get_streams(user_ids=list(callbacks.keys()), origin=AlertOrigin.catchup)
        # We only need the ID from them
        online_stream_uids = [str(stream.user.id) for stream in streams]

        # Iterate through all callbacks and update all streamers
        for streamer_id, callback_info in callbacks.items():
            if streamer_id in online_stream_uids:
                stream = [s for s in streams if s.user.id ==
                          int(streamer_id)][0]
                # Update display name if needed
                if callback_info["display_name"] != stream.user.display_name:
                    callback_info["display_name"] = stream.user.display_name
                    await self.db.write_callback(stream.user, callback_info)
                self.queue.put_nowait(stream)
            else:
                self.queue.put_nowait(PartialUser(
                    streamer_id, callback_info["display_name"].lower(), callback_info["display_name"]))


if __name__ == "__main__":
    bot = TwitchCallBackBot()
    bot.run(bot.token)
