from typing import TYPE_CHECKING

from disnake import Guild
from disnake.ext import commands

from twitchtools import YoutubeSubscription

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
        await self.bot.wait_until_db_ready()
        async for streamer, callback_info in self.bot.db.async_get_all_callbacks():
            if str(guild.id) in callback_info["alert_roles"].keys():
                del callback_info["alert_roles"][str(guild.id)]
                if callback_info["alert_roles"] == {}:
                    self.bot.log.info(
                        f"{callback_info['display_name']} is no longer enrolled in any alerts, purging callbacks and cache")
                    await self.bot.tapi.delete_subscription(callback_info['offline_id'])
                    await self.bot.tapi.delete_subscription(callback_info['online_id'])
                    await self.bot.tapi.delete_subscription(callback_info['title_id'])
                    await self.bot.db.delete_channel_cache(streamer)
                    await self.bot.db.delete_callback(streamer)
                else:
                    await self.bot.db.write_callback(streamer, callback_info)

        for channel, callback_info in (await self.bot.db.get_all_yt_callbacks()).items():
            if str(guild.id) in callback_info["alert_roles"].keys():
                del callback_info["alert_roles"][str(guild.id)]
                if callback_info["alert_roles"] == {}:
                    self.bot.log.info(
                        f"{callback_info['display_name']} is no longer enrolled in any alerts, purging callbacks and cache")
                    subscription = YoutubeSubscription(callback_info["subscription_id"], channel, callback_info["secret"])
                    await self.bot.yapi.delete_subscription(subscription)
                    await self.bot.db.delete_yt_channel_cache(channel)
                    await self.bot.db.delete_yt_callback(channel)
                else:
                    await self.bot.db.write_yt_callback(channel, callback_info)

        async for streamer, callback_info in self.bot.db.async_get_all_title_callbacks():
            if str(guild.id) in callback_info["alert_roles"].keys():
                    del callback_info["alert_roles"][str(guild.id)]
                    if callback_info["alert_roles"] == {}:
                        self.bot.log.info(
                            f"{callback_info['display_name']} is no longer enrolled in any alerts, purging callbacks and cache")
                        await self.bot.db.delete_title_cache(streamer)
                        await self.bot.db.delete_title_callback(streamer)
                    else:
                        await self.bot.db.write_callback(streamer, callback_info)

        await self.bot.db.delete_manager_role(guild)


def setup(bot):
    bot.add_cog(CallbackCleanup(bot))
