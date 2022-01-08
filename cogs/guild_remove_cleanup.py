from disnake import Guild
from disnake.ext import commands
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import TwitchCallBackBot

class CallbackCleanup(commands.Cog):
    from twitchtools.files import get_callbacks, write_callbacks, get_title_callbacks, write_title_callbacks
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: Guild):
        callbacks = await self.get_callbacks()
        diff = False
        for streamer, callback_info in dict(callbacks).items():
            if str(guild.id) in callback_info["alert_roles"].keys():
                try:
                    del callback_info["alert_roles"][str(guild.id)]
                    diff = True
                    if callback_info["alert_roles"] == {}:
                        self.bot.log.info(f"Streamer {streamer} has no more alerts, purging")
                        await self.bot.api.delete_subscription(callbacks[streamer]['offline_id'])
                        await self.bot.api.delete_subscription(callbacks[streamer]['online_id'])
                        del callbacks[streamer]
                except KeyError: # Idk if it somehow errors lol, just ignore
                    continue
        if diff:
            await self.write_callbacks(callbacks)

        title_callbacks = await self.get_title_callbacks()
        tdiff = False
        for streamer, callback_info in dict(title_callbacks).items():
            if str(guild.id) in callback_info["alert_roles"].keys():
                try:
                    del callback_info["alert_roles"][str(guild.id)]
                    tdiff = True
                    if callback_info["alert_roles"] == {}:
                        self.bot.log.info(f"Streamer {streamer} has no more alerts, purging")
                        await self.bot.api.delete_subscription(callbacks[streamer]['subscription_id'])
                        del callbacks[streamer]
                except KeyError: # Idk if it somehow errors lol, just ignore
                    continue
        if tdiff:
            await self.write_title_callbacks(callbacks)


def setup(bot):
    bot.add_cog(CallbackCleanup(bot))