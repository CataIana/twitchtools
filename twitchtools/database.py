from disnake import Guild
from disnake.ext import commands
import motor.motor_asyncio
from .exceptions import DBConnectionError, NoToken
from collections import deque
from typing import TYPE_CHECKING, Deque
if TYPE_CHECKING:
    from main import TwitchCallBackBot


class DB(commands.Cog, name="Database Cog"):
    def __init__(self, bot, connection_uri: str):
        self.bot: TwitchCallBackBot = bot
        self._timeout: int = 5000
        self._uri: str = connection_uri
        self._connected: bool = False

    async def connect(self):
        """Initialise the connection to the database"""
        self._mongo = motor.motor_asyncio.AsyncIOMotorClient(self._uri, serverSelectionTimeoutMS=self._timeout)
        try:
            await self._mongo.server_info()
            self._db = self._mongo["twitchtools"]
            self._connected = True
        except Exception:
            raise DBConnectionError

    # async def remove_guild(self, guild: Guild) -> dict:
    #     """Removes an existing guild. Returns None on success"""
    #     if not self._connected:
    #         raise DBConnectionError("Not connected to database!")
    #     result = await self._db.guilds.find_one_and_delete({"guild_id": guild.id})
    #     if not result:
    #         raise GuildNotFound(guild)
    #     return result

    async def write_token(self, token: str):
        """Update the stored twitch access token"""
        if not self._connected:
            raise DBConnectionError("Not connected to database!")
        result = await self._db.token.update_one({"_id": "token_storage"}, {"$set": {"token": token}})
        if result.matched_count == 0:
            await self._db.token.insert_one({"_id": "token_storage", "token": token})

    async def get_token(self) -> str:
        if not self._connected:
            raise DBConnectionError("Not connected to database!")
        token = await self._db.guilds.find_one({"_id": "token_storage"})
        try:
            if token:
                return token["token"]
        except KeyError:
            pass
        raise NoToken
    
    async def get_title_callback(self, streamer: str) -> dict:
        if not self._connected:
            raise DBConnectionError("Not connected to database!")
        return await self._db.titles.find_one({"_id": streamer})

    async def get_callback(self) -> dict:
        pass

    async def write_title_callback(self, streamer: str, callback: dict):
        result = await self._db.titles.update({"_id": streamer}, {"$set": callback})
        if result.matched_count == 0:
            callback.update({"_id": streamer})
            await self._db.titles.insert_one(callback)

    async def write_callback(self, streamer: str, callback: dict):
        result = await self._db.callbacks.update({"_id": streamer}, {"$set": callback})
        if result.matched_count == 0:
            callback.update({"_id": streamer})
            await self._db.callbacks.insert_one(callback)

    async def get_channel_cache(self) -> list:
        pass

    async def write_channel_cache(self, list: list):
        pass

    async def get_title_cache(self) -> list:
        pass

    async def write_title_cache(self, list: list):
        pass

    async def get_notification_cache(self) -> Deque[str]:
        if not self._connected:
            raise DBConnectionError("Not connected to database!")
        notif_cache = await self._db.cache.find_one({"_id": "notification_cache"})
        if notif_cache:
            return Deque(notif_cache.get('cache', []), maxlen=10)
        return Deque([], maxlen=10)

    async def write_notification_cache(self, notif_cache: Deque[str]):
        if not self._connected:
            raise DBConnectionError("Not connected to database!")
        result = await self._db.cache.update_one({"_id": "notification_cache"}, {"$set": {"cache": list(notif_cache)}})
        if result.matched_count == 0:
            await self._db.cache.insert_one({"_id": "notification_cache", "cache": list(notif_cache)})