from __future__ import annotations

import json
import logging
import sys
from asyncio import Event, Queue
from enum import Enum
from random import choice
from string import ascii_letters
from time import time
from typing import Any, Type, TypeVar, Union

import disnake
from aiohttp import ClientSession
from disnake.ext import commands

from cogs.database import DB
from cogs.webserver import RecieverWebServer
from twitchtools import (AlertOrigin, BadAuthorization, CustomConnectionState,
                         PartialUser, PartialYoutubeUser, Ratelimit,
                         http_twitch, http_youtube)

ACXT = TypeVar(
    "ACXT", bound="disnake.interactions.ApplicationCommandInteraction")


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
        self.loop.run_until_complete(self.web_server.start())

        self.db_connect_uri = config["mongodb_uri"]
        self._db_ready: Event = Event()
        self.db: DB

        self.load_extension("cogs.database")
        self.load_extension("cogs.state_manager")
        self.load_extension("cogs.queue_handler")
        self.load_extension("cogs.commands")
        self.load_extension("cogs.twitch_commands")
        self.load_extension("cogs.youtube_commands")
        self.load_extension("cogs.error_listener")
        self.load_extension("cogs.guild_remove_cleanup")
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
            self.ratelimits[streamer.id] = Ratelimit(calls=10, period=600, display_name=streamer.display_name)
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

    async def twitch_catchup(self):
        await self.wait_until_ready()
        await self.wait_until_db_ready()
        callbacks = await self.db.get_all_callbacks()
        if callbacks == {}:
            return

        # Fetch all streamers, returning the currently live ones
        streams = await self.tapi.get_streams(user_ids=list(callbacks.keys()), origin=AlertOrigin.catchup)
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

    async def youtube_catchup(self):
        await self.wait_until_ready()
        await self.wait_until_db_ready()
        callbacks = await self.db.get_all_yt_callbacks()
        if callbacks == {}:
            return

        # Get all caches, saves multiple DB calls for same data
        caches = {c: await self.db.get_yt_channel_cache(c) for c in callbacks.keys()}

        # Offline -> online handling

        # Filter live channels out
        non_live_channels = [c for c in callbacks.keys(
        ) if not caches[c].get("is_live", False)]
        # Fetch recent video IDs from each channel. No API cost. Only check non live channels. Returns dict[channel, list[video_id]]
        recent_vids = await self.yapi.get_recent_video_ids(non_live_channels)
        # Returns dict containing each channel as key and video id as value. Return empty dict if none
        new_live_channels = await self.yapi.are_videos_live(recent_vids)

        # Online -> offline handling

        # Fetch all channels that are live. Returns list of video_ids that have ended
        live_videos_cached = [
            caches[c].video_id for c in callbacks.keys() if caches[c].get("is_live", False)]
        ended_videos = await self.yapi.have_videos_ended(live_videos_cached)

        # Iterate through all callbacks and update all streamers
        for channel, callback_info in callbacks.items():
            # If channel is live, check cached video to see if finished
            if channel not in non_live_channels:
                if caches[channel].video_id in ended_videos:
                    self.queue.put_nowait(channel)
                else:
                    video = await self.yapi.get_stream(caches[channel].video_id, alert_origin=AlertOrigin.catchup)
                    self.queue.put_nowait(video)
            else:
                # Otherwise, check if channel is live, and fetch video that is live
                if video_id := new_live_channels.get(channel, None):
                    video = await self.yapi.get_stream(video_id, alert_origin=AlertOrigin.catchup)
                    # Update display name if needed
                    if callback_info["display_name"] != video.user.display_name:
                        callback_info["display_name"] = video.user.display_name
                        await self.db.write_yt_callback(video.user, callback_info)
                    self.queue.put_nowait(video)
                else:
                    self.queue.put_nowait(channel)

    def random_string_generator(self, str_size):
        return "".join(choice(ascii_letters) for _ in range(str_size))


if __name__ == "__main__":
    bot = TwitchCallBackBot()
    bot.run(bot.token)
