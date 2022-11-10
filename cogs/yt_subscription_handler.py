from asyncio import sleep
from datetime import datetime
from typing import TYPE_CHECKING

from disnake.ext import commands, tasks

from twitchtools import PartialYoutubeUser, YoutubeCallback

if TYPE_CHECKING:
    from twitchtools import TwitchCallBackBot

LEASE_SECONDS = 828000


class YTSubscriptionHandler(commands.Cog, name="Youtube Subscription Handler"):
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()
        self.yt_check_expiry.start()

    def cog_unload(self):
        self.yt_check_expiry.cancel()

    @tasks.loop(hours=24)
    async def yt_check_expiry(self):
        await self.bot.wait_until_ready()
        await self.bot.wait_until_db_ready()
        self.bot.log.debug("Resubscribing youtube callbacks")
        for channel, channel_data in (await self.bot.db.get_all_yt_callbacks()).items():
            expiry_time = channel_data.get("expiry_time", 0)
            if expiry_time < datetime.utcnow().timestamp():
                self.bot.log.info(
                    f"Resubscribing YT channel {channel.display_name}")
                await self.yt_subscribe(channel, channel_data)

    async def yt_subscribe(self, channel: PartialYoutubeUser, channel_data: YoutubeCallback):
        await self.bot.yapi.create_subscription(channel, channel_data.secret, channel_data.subscription_id)
        # Minus a day plus 100 seconds, ensures that the subscription never expires
        timestamp = datetime.utcnow().timestamp() + (LEASE_SECONDS - 86500)
        await self.bot.db.write_yt_callback_expiration(channel, timestamp)
        # self.bot.log.info(f"Resubscribed {channel.display_name}")
        await sleep(0.25)


def setup(bot):
    bot.add_cog(YTSubscriptionHandler(bot))
