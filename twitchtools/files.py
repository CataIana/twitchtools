from disnake import Guild, Role
from typing import Deque, List, Union
import aiofiles
import os
import json
from collections import deque

# This is a now obsolete file, but it's still here in case


async def get_callbacks() -> dict:
    try:
        async with aiofiles.open("config/callbacks.json") as f:
            return json.loads(await f.read())
    except FileNotFoundError:
        return {}
    except json.decoder.JSONDecodeError:
        return {}


async def write_callbacks(data: dict) -> None:
    async with aiofiles.open("config/callbacks.json", "w") as f:
        await f.write(json.dumps(data, indent=4))


async def get_title_callbacks() -> dict:
    try:
        async with aiofiles.open("config/title_callbacks.json") as f:
            return json.loads(await f.read())
    except FileNotFoundError:
        return {}
    except json.decoder.JSONDecodeError:
        return {}


async def write_title_callbacks(data: dict) -> None:
    async with aiofiles.open("config/title_callbacks.json", "w") as f:
        await f.write(json.dumps(data, indent=4))


async def get_channel_cache() -> dict:
    try:
        async with aiofiles.open("cache/channelcache.cache") as f:
            return json.loads(await f.read())
    except FileNotFoundError:
        return {}
    except json.decoder.JSONDecodeError:
        return {}


async def write_channel_cache(data: dict) -> None:
    if not os.path.isdir("cache"):
        os.mkdir("cache")
    async with aiofiles.open("cache/channelcache.cache", "w") as f:
        await f.write(json.dumps(data, indent=4))


async def get_title_cache() -> dict:
    try:
        async with aiofiles.open("cache/titlecache.cache") as f:
            return json.loads(await f.read())
    except FileNotFoundError:
        return {}
    except json.decoder.JSONDecodeError:
        return {}


async def write_title_cache(data: dict) -> None:
    if not os.path.isdir("cache"):
        os.mkdir("cache")
    async with aiofiles.open("cache/titlecache.cache", "w") as f:
        await f.write(json.dumps(data, indent=4))


async def get_notif_cache() -> Deque:
    try:
        async with aiofiles.open("cache/notifcache.cache") as f:
            return deque(json.loads(await f.read()), maxlen=10)
    except FileNotFoundError:
        return []
    except json.decoder.JSONDecodeError:
        return []


async def write_notif_cache(data: Union[Deque, List]) -> None:
    if not os.path.isdir("cache"):
        os.mkdir("cache")
    async with aiofiles.open("cache/notifcache.cache", "w") as f:
        await f.write(json.dumps(list(data), indent=4))


async def get_manager_role(guild: Guild) -> int:
    try:
        async with aiofiles.open("config/manager_roles.json") as f:
            data = json.loads(await f.read())
        return data.get(str(guild.id), None)
    except FileNotFoundError:
        return None
    except json.decoder.JSONDecodeError:
        return None


async def write_manager_role(guild: Guild, role: Role = None) -> None:
    if not os.path.isdir("config"):
        os.mkdir("config")
    try:
        async with aiofiles.open("config/manager_roles.json") as f:
            data = json.loads(await f.read())
    except FileNotFoundError:
        data = {}
    except json.decoder.JSONDecodeError:
        data = {}
    if role:
        data.update({str(guild.id): role.id})
    else:
        try:
            del data[str(guild.id)]
        except KeyError:
            return

    async with aiofiles.open("config/manager_roles.json", "w") as f:
        await f.write(json.dumps(data, indent=4))
