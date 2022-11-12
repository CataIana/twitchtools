from asyncio import sleep
from collections import deque
from typing import TYPE_CHECKING, Deque, Generator, Optional, Union

import motor.motor_asyncio
from disnake import Guild, Role
from disnake.ext import commands
from munch import munchify
from pymongo.errors import ServerSelectionTimeoutError

from twitchtools.enums import (Callback, ChannelCache, TitleCache,
                               TitleCallback, YoutubeCallback,
                               YoutubeChannelCache)
from twitchtools.exceptions import DBConnectionError
from twitchtools.user import PartialUser, PartialYoutubeUser, User
from twitchtools.video import YoutubeVideo

if TYPE_CHECKING:
    from main import TwitchCallBackBot


class DB(commands.Cog, name="Database Cog"):
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()
        self._timeout: int = 5000
        self._uri: str = self.bot.db_connect_uri
        self.bot.db = self
        self.trying_to_connect = False

    @property
    def is_connected(self) -> bool:
        return self.bot._db_ready.is_set()

    @commands.Cog.listener()
    async def on_connect(self):
        self.db_name = f"twitchtools-{self.bot.user.id}"
        await self.connect()

    def cog_unload(self):
        if self.is_connected:
            self.bot.log.info("[Database] Disconnecting")
            self.bot._db_ready.clear()
            self._mongo.close()
            self.bot.db = None

    async def connect(self):
        """Initialise the connection to the database"""
        self._mongo = motor.motor_asyncio.AsyncIOMotorClient(
            self._uri, serverSelectionTimeoutMS=self._timeout)
        failed_attempts = 0
        self.trying_to_connect = True
        while not self.is_connected and not self.bot.is_closed():
            try:
                await self._mongo.server_info()
                self._db: motor.motor_asyncio.core.AgnosticDatabase = self._mongo[self.db_name]
                self.bot._db_ready.set()
                self.bot.log.info(f"[Database] Connected ({self.db_name})")
            except ServerSelectionTimeoutError as e:
                self.bot.log.error(f"[Database] Failed to connect! {e._message}")
                # Multiply exponentially with max wait of 2 minutes
                await sleep(min((120, 2**failed_attempts)))
                failed_attempts += 1
        self.trying_to_connect = False

    async def check_connect(self):
        if not self.is_connected and not self.trying_to_connect:
            self.bot.log.info(f"DB is not connected, reconnecting...")
            await self.connect()
            if not self.is_connected:
                raise DBConnectionError

    async def write_access_token(self, token: str):
        await self.check_connect()
        result = await self._db.token.update_one({"_id": "access_token"}, {"$set": {"token": token}})
        if result.matched_count == 0:
            await self._db.token.insert_one({"_id": "access_token", "token": token})

    async def get_access_token(self) -> Optional[str]:
        await self.check_connect()
        token = await self._db.token.find_one({"_id": "access_token"})
        if token:
            return token.get("token", None)
        return None

    async def get_callback(self, broadcaster: PartialUser) -> Optional[Callback]:
        await self.check_connect()
        callback = await self._db.callbacks.find_one({"_id": str(broadcaster.id)})
        if callback:
            return munchify(callback)
        return None

    async def get_callback_by_id(self, broadcaster_id: int) -> Optional[Callback]:
        await self.check_connect()
        callback = await self._db.callbacks.find_one({"_id": str(broadcaster_id)})
        if callback:
            return munchify(callback)
        return None

    async def write_callback(self, broadcaster: PartialUser, callback: Callback):
        await self.check_connect()
        callback = dict(callback)
        result = await self._db.callbacks.update_one({"_id": str(broadcaster.id)}, {"$set": callback})
        if result.matched_count == 0:
            callback.update({"_id": str(broadcaster.id)})
            await self._db.callbacks.insert_one(callback)

    async def async_get_all_callbacks(self) -> Generator[tuple[User, Callback], None, None]:
        await self.check_connect()
        async for document in self._db.callbacks.find({"_id": {"$exists": True}}):
            broadcaster = await self.bot.tapi.get_user(user_id=document["_id"])
            yield broadcaster, munchify(document)

    async def get_all_callbacks(self) -> dict[str, Callback]:
        await self.check_connect()
        cursor = self._db.callbacks.find({"_id": {"$exists": True}})
        count = await self._db.callbacks.count_documents({})
        documents = await cursor.to_list(length=count)
        return {d["_id"]: munchify(d) for d in documents}

    async def delete_callback(self, broadcaster: PartialUser):
        await self.check_connect()
        return await self._db.callbacks.find_one_and_delete({"_id": str(broadcaster.id)})

    async def get_title_callback(self, broadcaster: PartialUser) -> Optional[TitleCallback]:
        await self.check_connect()
        callback = await self._db.tcallbacks.find_one({"_id": str(broadcaster.id)})
        if callback:
            return munchify(callback)
        return None

    async def get_title_callback_by_id(self, broadcaster_id: int) -> Optional[TitleCallback]:
        await self.check_connect()
        callback = await self._db.tcallbacks.find_one({"_id": str(broadcaster_id)})
        if callback:
            return munchify(callback)
        return None

    async def write_title_callback(self, broadcaster: PartialUser, callback: TitleCallback):
        await self.check_connect()
        callback = dict(callback)
        #result = await self._db.tcallbacks.update_one({"_id": str(broadcaster.id)}, {"$set": callback})
        result = await self._db.tcallbacks.replace_one({"_id": str(broadcaster.id)}, callback)
        if result.matched_count == 0:
            callback.update({"_id": str(broadcaster.id)})
            await self._db.tcallbacks.insert_one(callback)

    async def async_get_all_title_callbacks(self) -> Generator[tuple[User, TitleCallback], None, None]:
        await self.check_connect()
        async for document in self._db.tcallbacks.find({"_id": {"$exists": True}}):
            broadcaster = await self.bot.tapi.get_user(user_id=document["_id"])
            yield broadcaster, munchify(document)

    async def get_all_title_callbacks(self) -> dict[str, TitleCallback]:
        await self.check_connect()
        cursor = self._db.tcallbacks.find({"_id": {"$exists": True}})
        count = await self._db.tcallbacks.count_documents({})
        documents = await cursor.to_list(length=count)
        return {d["_id"]: munchify(d) for d in documents}

    async def delete_title_callback(self, broadcaster: PartialUser):
        await self.check_connect()
        return await self._db.tcallbacks.find_one_and_delete({"_id": str(broadcaster.id)})

    async def get_channel_cache(self, broadcaster: PartialUser) -> Optional[ChannelCache]:
        await self.check_connect()
        channel_cache = await self._db.ccache.find_one({"_id": str(broadcaster.id)})
        if channel_cache:
            return munchify(channel_cache)
        return munchify({})

    async def write_channel_cache(self, broadcaster: PartialUser, data: Union[ChannelCache, dict]):
        await self.check_connect()
        datad = dict(data)
        result = await self._db.ccache.replace_one({"_id": str(broadcaster.id)}, datad)
        if result.matched_count == 0:
            datad.update({"_id": str(broadcaster.id)})
            await self._db.ccache.insert_one(datad)

    async def delete_channel_cache(self, broadcaster: PartialUser):
        await self.check_connect()
        return await self._db.ccache.find_one_and_delete({"_id": str(broadcaster.id)})

    async def get_title_cache(self, broadcaster: PartialUser) -> TitleCache:
        await self.check_connect()
        title_cache = await self._db.tcache.find_one({"_id": str(broadcaster.id)})
        if title_cache:
            return munchify(title_cache)
        return munchify({"title": "<no title>", "game": "<no game>"})

    async def write_title_cache(self, broadcaster: PartialUser, cache: TitleCache):
        await self.check_connect()
        result = await self._db.tcache.update_one({"_id": str(broadcaster.id)}, {"$set": {"title": cache.title, "game": cache.game}})
        if result.matched_count == 0:
            await self._db.tcache.insert_one({"_id": str(broadcaster.id), "title": cache.title, "game": cache.game})

    async def delete_title_cache(self, broadcaster: PartialUser):
        await self.check_connect()
        return await self._db.tcache.find_one_and_delete({"_id": str(broadcaster.id)})

    async def get_notif_cache(self) -> Deque[str]:
        await self.check_connect()
        notif_cache = await self._db.ncache.find_one({"_id": "notification_cache"})
        if notif_cache:
            return deque(notif_cache.get('cache', []), maxlen=10)
        return deque([], maxlen=10)

    async def write_notif_cache(self, notif_cache: Deque[str]):
        await self.check_connect()
        result = await self._db.ncache.update_one({"_id": "notification_cache"}, {"$set": {"cache": list(notif_cache)}})
        if result.matched_count == 0:
            await self._db.ncache.insert_one({"_id": "notification_cache", "cache": list(notif_cache)})

    async def get_manager_role(self, guild: Guild) -> Optional[TitleCache]:
        await self.check_connect()
        role = await self._db.mrole.find_one({"_id": str(guild.id)})
        if role:
            return role.get("role_id", None)
        return None

    async def write_manager_role(self, guild: Guild, role: Role):
        await self.check_connect()
        result = await self._db.mrole.update_one({"_id": str(guild.id)}, {"$set": {"role_id": role.id}})
        if result.matched_count == 0:
            await self._db.mrole.insert_one({"_id": str(guild.id), "role_id": role.id})

    async def delete_manager_role(self, guild: Guild):
        await self.check_connect()
        return await self._db.mrole.find_one_and_delete({"_id": str(guild.id)})

    async def get_yt_callback(self, channel: PartialYoutubeUser) -> Optional[YoutubeCallback]:
        await self.check_connect()
        yt_callback = await self._db.yt_callbacks.find_one({"_id": channel.id})
        if yt_callback:
            return munchify(yt_callback)
        return None

    async def get_yt_callback_by_id(self, channel_id: str) -> Optional[YoutubeCallback]:
        await self.check_connect()
        yt_callback = await self._db.yt_callbacks.find_one({"_id": channel_id})
        if yt_callback:
            return munchify(yt_callback)
        return None

    async def write_yt_callback(self, channel: PartialYoutubeUser, callback: YoutubeCallback):
        await self.check_connect()
        callback = dict(callback)
        result = await self._db.yt_callbacks.update_one({"_id": channel.id}, {"$set": callback})
        if result.matched_count == 0:
            callback.update({"_id": channel.id})
            await self._db.yt_callbacks.insert_one(callback)

    async def write_yt_callback_expiration(self, channel: PartialYoutubeUser, timestamp: int):
        await self.check_connect()
        callback = await self.get_yt_callback(channel)
        if callback:
            callback.expiry_time = int(timestamp)
            await self.write_yt_callback(channel, dict(callback))

    async def get_all_yt_callbacks(self) -> dict[PartialYoutubeUser, YoutubeCallback]:
        await self.check_connect()
        cursor = self._db.yt_callbacks.find({"_id": {"$exists": True}})
        count = await self._db.yt_callbacks.count_documents({})
        documents = await cursor.to_list(length=count)
        return {PartialYoutubeUser(d["_id"], d["display_name"]): munchify(d) for d in documents}

    async def delete_yt_callback(self, channel: PartialYoutubeUser):
        await self.check_connect()
        await self._db.yt_callbacks.find_one_and_delete({"_id": channel.id})

    async def get_last_yt_vid(self, channel: PartialYoutubeUser) -> Optional[dict]:
        await self.check_connect()
        cache_data = await self._db.yt_cache.find_one({"_id": channel.id})
        if cache_data:
            return cache_data
        return None

    async def update_last_yt_vid(self, video: YoutubeVideo):
        await self.check_connect()
        result = await self._db.yt_cache.replace_one({"_id": video.channel.id}, {"video_id": video.id, "publish_time": video.published_at.timestamp()})
        if result.matched_count == 0:
            await self._db.yt_cache.insert_one({"_id": video.channel.id, "video_id": video.id, "publish_time": video.published_at.timestamp()})

    async def get_yt_channel_cache(self, channel: PartialYoutubeUser) -> Optional[YoutubeChannelCache]:
        await self.check_connect()
        channel_cache = await self._db.yt_ccache.find_one({"_id": channel.id})
        if channel_cache:
            return munchify(channel_cache)
        return munchify({})

    async def write_yt_channel_cache(self, channel: PartialYoutubeUser, data: Union[ChannelCache, dict]):
        await self.check_connect()
        datad = dict(data)
        result = await self._db.yt_ccache.replace_one({"_id": channel.id}, datad)
        if result.matched_count == 0:
            datad.update({"_id": channel.id})
            await self._db.yt_ccache.insert_one(datad)

    async def delete_yt_channel_cache(self, channel: PartialYoutubeUser):
        await self.check_connect()
        return await self._db.yt_ccache.find_one_and_delete({"_id": channel.id})

    async def get_yt_title_cache(self, channel: PartialYoutubeUser) -> TitleCache:
        await self.check_connect()
        title_cache = await self._db.yt_tcache.find_one({"_id": channel.id})
        if title_cache:
            return munchify(title_cache)
        return munchify({"title": "<no title>"})

    async def write_yt_title_cache(self, channel: PartialYoutubeUser, cache: TitleCache):
        await self.check_connect()
        result = await self._db.yt_tcache.update_one({"_id": channel.id}, {"$set": {"title": cache.title}})
        if result.matched_count == 0:
            await self._db.yt_tcache.insert_one({"_id": channel.id, "title": cache.title})

    async def delete_yt_title_cache(self, channel: PartialYoutubeUser):
        await self.check_connect()
        return await self._db.yt_tcache.find_one_and_delete({"_id": channel.id})

def setup(bot):
    bot.add_cog(DB(bot))
