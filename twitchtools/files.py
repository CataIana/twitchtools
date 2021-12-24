from typing import Deque, List, Union
import aiofiles
import os
import json
from collections import deque

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
    if not os.path.isdir("cache"):
        os.mkdir("cache")
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
    if not os.path.isdir("cache"):
        os.mkdir("cache")
    async with aiofiles.open("cache/titlecache.cache", "w") as f:
        await f.write(json.dumps(data, indent=4))

async def get_notif_cache(self) -> Deque:
    try:
        async with aiofiles.open("cache/notifcache.cache") as f:
            return deque(json.loads(await f.read()), maxlen=10)
    except FileNotFoundError:
        return []
    except json.decoder.JSONDecodeError:
        return []

async def write_notif_cache(self, data: Union[Deque, List]) -> None:
    if not os.path.isdir("cache"):
        os.mkdir("cache")
    async with aiofiles.open("cache/notifcache.cache", "w") as f:
        await f.write(json.dumps(list(data), indent=4))