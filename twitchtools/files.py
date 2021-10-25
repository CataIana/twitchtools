import aiofiles
import json
from typing import Union

async def get_callbacks(self) -> dict:
    try:
        async with aiofiles.open("config/callbacks.json") as f:
            return json.loads(await f.read())
    except FileNotFoundError:
        return {}
    except json.decoder.JSONDecodeError:
        return {}

async def write_callbacks(self, data: dict) -> None:
    async with aiofiles.open("config/callbacks.json", "w") as f:
        await f.write(json.dumps(data, indent=4))

async def get_title_callbacks(self) -> dict:
    try:
        async with aiofiles.open("config/title_callbacks.json") as f:
            return json.loads(await f.read())
    except FileNotFoundError:
        return {}
    except json.decoder.JSONDecodeError:
        return {}

async def write_title_callbacks(self, data: dict) -> None:
    async with aiofiles.open("config/title_callbacks.json", "w") as f:
        await f.write(json.dumps(data, indent=4))

async def get_channel_cache(self) -> dict:
    try:
        async with aiofiles.open("cache/channelcache.cache") as f:
            return json.loads(await f.read())
    except FileNotFoundError:
        return {}
    except json.decoder.JSONDecodeError:
        return {}

async def write_channel_cache(self, data: dict) -> None:
    async with aiofiles.open("cache/channelcache.cache", "w") as f:
        await f.write(json.dumps(data, indent=4))

async def get_title_cache(self) -> dict:
    try:
        async with aiofiles.open("cache/titlecache.cache") as f:
            return json.loads(await f.read())
    except FileNotFoundError:
        return {}
    except json.decoder.JSONDecodeError:
        return {}

async def write_title_cache(self, data: dict) -> None:
    async with aiofiles.open("cache/titlecache.cache", "w") as f:
        await f.write(json.dumps(data, indent=4))

async def get_notif_cache(self) -> list:
    try:
        async with aiofiles.open("cache/notifcache.cache") as f:
            return json.loads(await f.read())
    except FileNotFoundError:
        return []
    except json.decoder.JSONDecodeError:
        return []

async def write_notif_cache(self, data: list) -> None:
    async with aiofiles.open("cache/notifcache.cache", "w") as f:
        await f.write(json.dumps(data, indent=4))