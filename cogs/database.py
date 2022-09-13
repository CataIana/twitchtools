from disnake import Guild, Role
from disnake.ext import commands
import motor.motor_asyncio
from collections import deque
from twitchtools.exceptions import DBConnectionError
from twitchtools.enums import TitleCache, ChannelCache
from twitchtools.user import PartialUser, User
from munch import munchify
from typing import TYPE_CHECKING, Deque, Union, Generator
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

    async def get_access_token(self) -> str:
        if not self.is_connected:
            raise DBConnectionError
        token = await self._db.token.find_one({"_id": "access_token"})
        if token:
            return token.get("token", None)
        return None

    async def get_callback(self, broadcaster: PartialUser) -> dict:
        callback = await self._db.callbacks.find_one({"_id": str(broadcaster.id)})
        if callback:
            return callback
        return None

    async def write_callback(self, broadcaster: PartialUser, callback: dict):
        result = await self._db.callbacks.update_one({"_id": str(broadcaster.id)}, {"$set": callback})
        if result.matched_count == 0:
            callback.update({"_id": str(broadcaster.id)})
            await self._db.callbacks.insert_one(callback)

    async def async_get_all_callbacks(self) -> Generator[tuple[User, dict], None, None]:
        async for document in self._db.callbacks.find({"_id": {"$exists": True}}):
            broadcaster = await self.bot.api.get_user(user_id=document["_id"])
            yield broadcaster, document

    async def get_all_callbacks(self) -> dict[str, dict]:
        cursor = self._db.callbacks.find({"_id": {"$exists": True}})
        count = await self._db.callbacks.count_documents({})
        documents = await cursor.to_list(length=count)
        return {d["_id"]: d for d in documents}

    async def delete_callback(self, broadcaster: PartialUser):
        return await self._db.callbacks.find_one_and_delete({"_id": str(broadcaster.id)})

    async def get_title_callback(self, broadcaster: PartialUser) -> dict:
        callback = await self._db.tcallbacks.find_one({"_id": str(broadcaster.id)})
        if callback:
            return callback
        return None

    async def write_title_callback(self, broadcaster: PartialUser, callback: dict):
        result = await self._db.tcallbacks.update_one({"_id": str(broadcaster.id)}, {"$set": callback})
        if result.matched_count == 0:
            callback.update({"_id": str(broadcaster.id)})
            await self._db.tcallbacks.insert_one(callback)

    async def async_get_all_title_callbacks(self) -> Generator[tuple[User, dict], None, None]:
        async for document in self._db.tcallbacks.find({"_id": {"$exists": True}}):
            broadcaster = await self.bot.api.get_user(user_id=document["_id"])
            yield broadcaster, document

    async def get_all_title_callbacks(self) -> dict[str, dict]:
        cursor = self._db.tcallbacks.find({"_id": {"$exists": True}})
        count = await self._db.tcallbacks.count_documents({})
        documents = await cursor.to_list(length=count)
        return {d["_id"]: d for d in documents}

    async def delete_title_callback(self, broadcaster: PartialUser):
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

    async def get_manager_role(self, guild: Guild) -> TitleCache:
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
        return await self._db.mrole.find_one_and_delete({"_id": str(guild.id)})


def setup(bot):
    bot.add_cog(DB(bot))
