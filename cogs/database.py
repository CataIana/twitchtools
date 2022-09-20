from collections import deque
from typing import TYPE_CHECKING, Deque, Generator, Optional, Union

import motor.motor_asyncio
from disnake import Guild, Role
from disnake.ext import commands
from munch import munchify

from twitchtools.enums import ChannelCache, TitleCache, YoutubeChannelCache
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
        self.bot.loop.create_task(self.connect())

    @property
    def is_connected(self) -> bool:
        return self.bot._db_ready.is_set()

    def cog_unload(self):
        self.bot.log.info("Disconnecting from DB")
        self.bot._db_ready.clear()
        self._mongo.close()
        self.bot.db = None

    async def connect(self):
        """Initialise the connection to the database"""
        self._mongo = motor.motor_asyncio.AsyncIOMotorClient(
            self._uri, serverSelectionTimeoutMS=self._timeout)
        try:
            await self._mongo.server_info()
            self._db: motor.motor_asyncio.core.AgnosticDatabase = self._mongo["twitchtools"]
            self.bot._db_ready.set()
            self.bot.log.info("Connected to database")
        except Exception as e:
            raise DBConnectionError(str(e))

    async def write_access_token(self, token: str):
        if not self.is_connected:
            raise DBConnectionError
        result = await self._db.token.update_one({"_id": "access_token"}, {"$set": {"token": token}})
        if result.matched_count == 0:
            await self._db.token.insert_one({"_id": "access_token", "token": token})

    async def get_access_token(self) -> Optional[str]:
        if not self.is_connected:
            raise DBConnectionError
        token = await self._db.token.find_one({"_id": "access_token"})
        if token:
            return token.get("token", None)
        return None

    async def get_callback(self, broadcaster: PartialUser) -> Optional[dict]:
        if not self.is_connected:
            raise DBConnectionError
        callback = await self._db.callbacks.find_one({"_id": str(broadcaster.id)})
        if callback:
            return callback
        return None

    async def get_callback_by_id(self, broadcaster_id: int) -> Optional[dict]:
        if not self.is_connected:
            raise DBConnectionError
        callback = await self._db.callbacks.find_one({"_id": str(broadcaster_id)})
        if callback:
            return callback
        return None

    async def write_callback(self, broadcaster: PartialUser, callback: dict):
        if not self.is_connected:
            raise DBConnectionError
        result = await self._db.callbacks.update_one({"_id": str(broadcaster.id)}, {"$set": callback})
        if result.matched_count == 0:
            callback.update({"_id": str(broadcaster.id)})
            await self._db.callbacks.insert_one(callback)

    async def async_get_all_callbacks(self) -> Generator[tuple[User, dict], None, None]:
        if not self.is_connected:
            raise DBConnectionError
        async for document in self._db.callbacks.find({"_id": {"$exists": True}}):
            broadcaster = await self.bot.tapi.get_user(user_id=document["_id"])
            yield broadcaster, document

    async def get_all_callbacks(self) -> dict[str, dict]:
        if not self.is_connected:
            raise DBConnectionError
        cursor = self._db.callbacks.find({"_id": {"$exists": True}})
        count = await self._db.callbacks.count_documents({})
        documents = await cursor.to_list(length=count)
        return {d["_id"]: d for d in documents}

    async def delete_callback(self, broadcaster: PartialUser):
        if not self.is_connected:
            raise DBConnectionError
        return await self._db.callbacks.find_one_and_delete({"_id": str(broadcaster.id)})

    async def get_title_callback(self, broadcaster: PartialUser) -> Optional[dict]:
        if not self.is_connected:
            raise DBConnectionError
        callback = await self._db.tcallbacks.find_one({"_id": str(broadcaster.id)})
        if callback:
            return callback
        return None

    async def get_title_callback_by_id(self, broadcaster_id: int) -> Optional[dict]:
        if not self.is_connected:
            raise DBConnectionError
        callback = await self._db.tcallbacks.find_one({"_id": str(broadcaster_id)})
        if callback:
            return callback
        return None

    async def write_title_callback(self, broadcaster: PartialUser, callback: dict):
        if not self.is_connected:
            raise DBConnectionError
        #result = await self._db.tcallbacks.update_one({"_id": str(broadcaster.id)}, {"$set": callback})
        result = await self._db.tcallbacks.replace_one({"_id": str(broadcaster.id)}, callback)
        if result.matched_count == 0:
            callback.update({"_id": str(broadcaster.id)})
            await self._db.tcallbacks.insert_one(callback)

    async def async_get_all_title_callbacks(self) -> Generator[tuple[User, dict], None, None]:
        if not self.is_connected:
            raise DBConnectionError
        async for document in self._db.tcallbacks.find({"_id": {"$exists": True}}):
            broadcaster = await self.bot.tapi.get_user(user_id=document["_id"])
            yield broadcaster, document

    async def get_all_title_callbacks(self) -> dict[str, dict]:
        if not self.is_connected:
            raise DBConnectionError
        cursor = self._db.tcallbacks.find({"_id": {"$exists": True}})
        count = await self._db.tcallbacks.count_documents({})
        documents = await cursor.to_list(length=count)
        return {d["_id"]: d for d in documents}

    async def delete_title_callback(self, broadcaster: PartialUser):
        if not self.is_connected:
            raise DBConnectionError
        return await self._db.tcallbacks.find_one_and_delete({"_id": str(broadcaster.id)})

    async def get_channel_cache(self, broadcaster: PartialUser) -> ChannelCache:
        if not self.is_connected:
            raise DBConnectionError
        channel_cache = await self._db.ccache.find_one({"_id": str(broadcaster.id)})
        if channel_cache:
            return munchify(channel_cache)
        return munchify({})

    async def write_channel_cache(self, broadcaster: PartialUser, data: Union[ChannelCache, dict]):
        if not self.is_connected:
            raise DBConnectionError
        datad = dict(data)
        result = await self._db.ccache.replace_one({"_id": str(broadcaster.id)}, datad)
        if result.matched_count == 0:
            datad.update({"_id": str(broadcaster.id)})
            await self._db.ccache.insert_one(datad)

    async def delete_channel_cache(self, broadcaster: PartialUser):
        return await self._db.ccache.find_one_and_delete({"_id": str(broadcaster.id)})

    async def get_title_cache(self, broadcaster: PartialUser) -> TitleCache:
        if not self.is_connected:
            raise DBConnectionError
        title_cache = await self._db.tcache.find_one({"_id": str(broadcaster.id)})
        if title_cache:
            return munchify(title_cache)
        return munchify({"title": "<no title>", "game": "<no game>"})

    async def write_title_cache(self, broadcaster: PartialUser, cache: TitleCache):
        if not self.is_connected:
            raise DBConnectionError
        result = await self._db.tcache.update_one({"_id": str(broadcaster.id)}, {"$set": {"title": cache.title, "game": cache.game}})
        if result.matched_count == 0:
            await self._db.tcache.insert_one({"_id": str(broadcaster.id), "title": cache.title, "game": cache.game})

    async def delete_title_cache(self, broadcaster: PartialUser):
        return await self._db.tcache.find_one_and_delete({"_id": str(broadcaster.id)})

    async def get_notif_cache(self) -> Deque[str]:
        if not self.is_connected:
            raise DBConnectionError
        notif_cache = await self._db.ncache.find_one({"_id": "notification_cache"})
        if notif_cache:
            return deque(notif_cache.get('cache', []), maxlen=10)
        return deque([], maxlen=10)

    async def write_notif_cache(self, notif_cache: Deque[str]):
        if not self.is_connected:
            raise DBConnectionError
        result = await self._db.ncache.update_one({"_id": "notification_cache"}, {"$set": {"cache": list(notif_cache)}})
        if result.matched_count == 0:
            await self._db.ncache.insert_one({"_id": "notification_cache", "cache": list(notif_cache)})

    async def get_manager_role(self, guild: Guild) -> Optional[TitleCache]:
        if not self.is_connected:
            raise DBConnectionError
        role = await self._db.mrole.find_one({"_id": str(guild.id)})
        if role:
            return role.get("role_id", None)
        return None

    async def write_manager_role(self, guild: Guild, role: Role):
        if not self.is_connected:
            raise DBConnectionError
        result = await self._db.mrole.update_one({"_id": str(guild.id)}, {"$set": {"role_id": role.id}})
        if result.matched_count == 0:
            await self._db.mrole.insert_one({"_id": str(guild.id), "role_id": role.id})

    async def delete_manager_role(self, guild: Guild):
        if not self.is_connected:
            raise DBConnectionError
        return await self._db.mrole.find_one_and_delete({"_id": str(guild.id)})

    async def get_yt_callback(self, channel: PartialYoutubeUser) -> Optional[dict]:
        if not self.is_connected:
            raise DBConnectionError
        yt_callback = await self._db.yt_callbacks.find_one({"_id": channel.id})
        if yt_callback:
            return yt_callback
        return None

    async def get_yt_callback_by_id(self, channel_id: str) -> Optional[dict]:
        if not self.is_connected:
            raise DBConnectionError
        yt_callback = await self._db.yt_callbacks.find_one({"_id": channel_id})
        if yt_callback:
            return yt_callback
        return None

    async def write_yt_callback(self, channel: PartialYoutubeUser, callback: dict):
        if not self.is_connected:
            raise DBConnectionError
        result = await self._db.yt_callbacks.update_one({"_id": channel.id}, {"$set": callback})
        if result.matched_count == 0:
            callback.update({"_id": channel.id})
            await self._db.yt_callbacks.insert_one(callback)

    async def write_yt_callback_expiration(self, channel: PartialYoutubeUser, timestamp: int):
        if not self.is_connected:
            raise DBConnectionError
        callback = await self.get_yt_callback(channel)
        if callback:
            callback["expiry_time"] = int(timestamp)
            await self.write_yt_callback(channel, callback)

    async def get_all_yt_callbacks(self) -> dict[PartialYoutubeUser, dict]:
        if not self.is_connected:
            raise DBConnectionError
        cursor = self._db.yt_callbacks.find({"_id": {"$exists": True}})
        count = await self._db.yt_callbacks.count_documents({})
        documents = await cursor.to_list(length=count)
        return {PartialYoutubeUser(d["_id"], d["display_name"]): d for d in documents}

    async def delete_yt_callback(self, channel: PartialYoutubeUser):
        if not self.is_connected:
            raise DBConnectionError
        await self._db.yt_callbacks.find_one_and_delete({"_id": channel.id})

    async def get_last_yt_vid(self, channel: PartialYoutubeUser) -> Optional[dict]:
        if not self.is_connected:
            raise DBConnectionError
        cache_data = await self._db.yt_cache.find_one({"_id": channel.id})
        if cache_data:
            return cache_data
        return None

    async def update_last_yt_vid(self, channel: PartialYoutubeUser, video: YoutubeVideo):
        if not self.is_connected:
            raise DBConnectionError
        result = await self._db.yt_cache.replace_one({"_id": channel.id}, {"video_id": video.id, "publish_time": video.published_at.timestamp()})
        if result.matched_count == 0:
            await self._db.yt_cache.insert_one({"_id": channel.id, "video_id": video.id, "publish_time": video.published_at.timestamp()})

    async def get_yt_channel_cache(self, channel: PartialYoutubeUser) -> YoutubeChannelCache:
        if not self.is_connected:
            raise DBConnectionError
        channel_cache = await self._db.yt_ccache.find_one({"_id": channel.id})
        if channel_cache:
            return munchify(channel_cache)
        return munchify({})

    async def write_yt_channel_cache(self, channel: PartialYoutubeUser, data: Union[ChannelCache, dict]):
        if not self.is_connected:
            raise DBConnectionError
        datad = dict(data)
        result = await self._db.yt_ccache.replace_one({"_id": channel.id}, datad)
        if result.matched_count == 0:
            datad.update({"_id": channel.id})
            await self._db.yt_ccache.insert_one(datad)

    async def delete_yt_channel_cache(self, channel: PartialYoutubeUser):
        return await self._db.yt_ccache.find_one_and_delete({"_id": channel.id})

    async def get_yt_title_cache(self, channel: PartialYoutubeUser) -> TitleCache:
        if not self.is_connected:
            raise DBConnectionError
        title_cache = await self._db.yt_tcache.find_one({"_id": channel.id})
        if title_cache:
            return munchify(title_cache)
        return munchify({"title": "<no title>"})

    async def write_yt_title_cache(self, channel: PartialYoutubeUser, cache: TitleCache):
        if not self.is_connected:
            raise DBConnectionError
        result = await self._db.yt_tcache.update_one({"_id": channel.id}, {"$set": {"title": cache.title}})
        if result.matched_count == 0:
            await self._db.yt_tcache.insert_one({"_id": channel.id, "title": cache.title})

    async def delete_yt_title_cache(self, channel: PartialYoutubeUser):
        return await self._db.yt_tcache.find_one_and_delete({"_id": channel.id})

def setup(bot):
    bot.add_cog(DB(bot))
