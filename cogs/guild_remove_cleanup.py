from disnake import Guild
from disnake.ext import commands
from twitchtools import PartialUser
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import TwitchCallBackBot


class CallbackCleanup(commands.Cog):
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()

    @commands.Cog.listener()
    async def on_guild_join(self, guild: Guild):
        self.bot.log.info(f"Joined guild {guild.name} :)")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: Guild):
        self.bot.log.info(f"Left guild {guild.name} :(")
        async for streamer, callback_info in self.bot.db.async_get_all_callbacks():
            if str(guild.id) in callback_info["alert_roles"].keys():
                del callback_info["alert_roles"][str(guild.id)]
                if callback_info["alert_roles"] == {}:
                    self.bot.log.info(
                        f"Streamer {callback_info['display_name']} has no more alerts, purging")
                    await self.bot.api.delete_subscription(callback_info['offline_id'])
                    await self.bot.api.delete_subscription(callback_info['online_id'])
                    await self.bot.api.delete_subscription(callback_info['title_id'])
                    await self.bot.wait_until_db_ready()
                    await self.bot.db.delete_channel_cache(streamer)
                    await self.bot.db.delete_callback(streamer)
                else:
                    await self.bot.db.write_callback(streamer, callback_info)

        async for streamer, callback_info in self.bot.db.async_get_all_title_callbacks():
            if str(guild.id) in callback_info["alert_roles"].keys():
                    del callback_info["alert_roles"][str(guild.id)]
                    if callback_info["alert_roles"] == {}:
                        self.bot.log.info(
                            f"Streamer {callback_info['display_name']} has no more alerts, purging")
                        await self.bot.wait_until_db_ready()
                        await self.bot.db.delete_title_cache(streamer)
                        await self.bot.db.delete_title_callback(streamer)
                    else:
                        await self.bot.db.write_callback(streamer, callback_info)


def setup(bot):
    bot.add_cog(CallbackCleanup(bot))
