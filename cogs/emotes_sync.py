import json
from json.decoder import JSONDecodeError
from typing import TYPE_CHECKING, Union

import aiofiles
from disnake import Forbidden, HTTPException
from disnake.emoji import Emoji
from disnake.ext import commands, tasks

from twitchtools.user import User

if TYPE_CHECKING:
    from main import TwitchCallBackBot

class EmoteSync(commands.Cog):
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()
        self.sync_loop.start()

    def cog_unload(self):
        self.sync_loop.cancel()

    @tasks.loop(hours=24.0)
    async def sync_loop(self):
        await self.sync_emotes()

    async def sync_emotes(self):
        await self.bot.wait_until_ready()
        try:
            async with aiofiles.open("config/emote_sync.json") as f:
                emote_sync = json.loads(await f.read())
        except FileNotFoundError:
            return
        except JSONDecodeError:
            return
        self.bot.log.info("Starting emote sync...")
        for guild_id, data in dict(emote_sync).items():
            if data.get("streamer_id", None) is None:
                user: User = self.bot.tapi.get_user(
                    user_login=data["streamer"])
                if user is None:
                    self.bot.log.warning(f"Search for streamer {data['streamer']} returned nothing.")
                    continue
                emote_sync[guild_id]["streamer_id"] = str(user.id)
            else:
                user_id = data.get("streamer_id")
            self.bot.log.info(f"Syncing streamer {data['streamer']}")

            #FFZ
            ffz_r = await self.bot.aSession.get(f"https://api.frankerfacez.com/v1/room/id/{user_id}")
            ffz = await ffz_r.json()
            existing_ffz_ids = list(data.get("emotes", {}).get("ffz", {}).keys())
            for emote in ffz["sets"][str(ffz["room"]["set"])]["emoticons"]:
                if str(emote["id"]) not in existing_ffz_ids:
                    emote_sync = await self.ffz_add_to_discord(emote_sync, guild_id, emote)
            
            ffz_emote_ids = [str(emote["id"]) for emote in ffz["sets"][str(ffz["room"]["set"])]["emoticons"]] #List of emote IDS
            self.bot.log.debug(ffz_emote_ids)
            self.bot.log.debug(existing_ffz_ids)
            for id in existing_ffz_ids:
                if str(id) not in ffz_emote_ids:
                    emote_sync = await self.ffz_remove_from_discord(emote_sync, guild_id, id)

            # #BTTV
            bttv_r = await self.bot.aSession.get(f"https://api.betterttv.net/3/cached/users/twitch/{user_id}")
            bttv = await bttv_r.json()
            existing_bttv_ids = list(data.get("emotes", {}).get("bttv", {}).keys())
            self.bot.log.debug([emote['id'] for emote in bttv["sharedEmotes"]])
            self.bot.log.debug(existing_bttv_ids)
            for emote in bttv["sharedEmotes"]:
                if str(emote["id"]) not in existing_bttv_ids:
                    emote_sync = await self.bttv_add_to_discord(emote_sync, guild_id, emote)

            bttv_emote_ids = [str(emote["id"]) for emote in bttv["sharedEmotes"]] #List of emote IDS
            for id in existing_bttv_ids:
                if str(id) not in bttv_emote_ids:
                    emote_sync = await self.bttv_remove_from_discord(emote_sync, guild_id, id)

        self.bot.log.info("Finished syncing.")

        async with aiofiles.open("config/emote_sync.json", "w") as f:
            await f.write(json.dumps(emote_sync, indent=4))
        
    async def ffz_add_to_discord(self, emote_sync, guild_id, emote):
        guild = self.bot.get_guild(int(guild_id))
        if guild is not None:
            self.bot.log.info(f"Adding emote {emote['name']}")
            url = f"https:{emote['urls'][list(emote['urls'].keys())[-1]]}"
            emote_bytes_r = await self.bot.aSession.get(url)
            emote_bytes = await emote_bytes_r.read()
            if len(emote_bytes) > 261120:
                self.bot.log.warning(f"Failed adding emote {emote['name']}. Emote is too large!")
            try:
                d_emote = await guild.create_custom_emoji(name=emote["name"], image=emote_bytes, reason=f"{self.bot.user}: Synced from FFZ")
                if emote_sync[guild_id].get("emotes", None) is None:
                    emote_sync[guild_id]["emotes"] = {"ffz": {}, "bttv": {}}
                if emote_sync[guild_id]["emotes"].get("ffz", None) is None:
                    emote_sync[guild_id]["ffz"] = {}
                emote_sync[guild_id]["emotes"]["ffz"][str(emote["id"])] = d_emote.id
            except Forbidden:
                self.bot.log.error(f"Bot does not have permissions to manage emotes in {guild.name}!")
            except HTTPException as e:
                self.bot.log.warning(f"Exception adding emote {emote['name']} in guild {guild.name}: {e}")
            return emote_sync

    async def ffz_remove_from_discord(self, emote_sync, guild_id, id):
        guild = self.bot.get_guild(int(guild_id))
        if guild is not None:
            emote: Union[Emoji, None] = None
            emote_id = emote_sync[guild_id]["emotes"]["ffz"][id]
            for emoji in guild.emojis:
                if emoji.id == int(emote_id):
                    emote = emoji
            if emote is not None:
                self.bot.log.info(f"Removing emote with {emote.name}")
                await emote.delete()
            else:
                self.bot.log.warning(f"Failed to removed {emote_id} from {guild.name}")
            del emote_sync[guild_id]["emotes"]["ffz"][id]
            return emote_sync

    async def bttv_add_to_discord(self, emote_sync, guild_id, emote):
        guild = self.bot.get_guild(int(guild_id))
        if guild is not None:
            self.bot.log.info(f"Adding emote {emote['code']}")
            url = f"https://cdn.betterttv.net/emote/{emote['id']}/3x"
            emote_bytes_r = await self.bot.aSession.get(url)
            emote_bytes = await emote_bytes_r.read()
            if len(emote_bytes) > 261120:
                self.bot.log.warning(f"Failed adding emote {emote['name']}. Emote is too large!")
            try:
                d_emote = await guild.create_custom_emoji(name=emote["code"], image=emote_bytes, reason=f"{self.bot.user}: Synced from BTTV")
                if emote_sync[guild_id].get("emotes", None) is None:
                    emote_sync[guild_id]["emotes"] = {"ffz": {}, "bttv": {}}
                if emote_sync[guild_id]["emotes"].get("bttv", None) is None:
                    emote_sync[guild_id]["bttv"] = {}
                emote_sync[guild_id]["emotes"]["bttv"][str(emote["id"])] = d_emote.id
            except Forbidden:
                self.bot.log.error(f"Bot does not have permissions to manage emotes in {guild.name}!")
            except HTTPException as e:
                self.bot.log.warning(f"Exception adding emote {emote['code']} in guild {guild.name}: {e}")
            return emote_sync

    async def bttv_remove_from_discord(self, emote_sync, guild_id, id):
        guild = self.bot.get_guild(int(guild_id))
        if guild is not None:
            emote: Union[Emoji, None] = None
            emote_id = emote_sync[guild_id]["emotes"]["bttv"][id]
            for emoji in guild.emojis:
                if emoji.id == int(emote_id):
                    emote = emoji
            if emote is not None:
                self.bot.log.info(f"Removing emote with {emote.name}")
                await emote.delete()
            else:
                self.bot.log.warning(f"Failed to removed {emote_id} from {guild.name}")
            del emote_sync[guild_id]["emotes"]["bttv"][id]
            return emote_sync

def setup(bot):
    bot.add_cog(EmoteSync(bot))