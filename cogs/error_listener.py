from disnake.errors import Forbidden
from disnake.ext import commands
from traceback import format_exc, format_exception
from twitchtools.custom_context import ApplicationCustomContext
from twitchtools.exceptions import SubscriptionError
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import TwitchCallBackBot

class ErrorListener(commands.Cog):
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()

    @commands.Cog.listener()
    async def on_error(self, event, *args, **kwargs):
        channel = self.bot.get_guild(749646865531928628).get_channel(763351494685884446)
        self.bot.log.error(format_exc())
        await channel.send(f"```python\n{format_exc()[:1982]}\n```")

    @commands.Cog.listener()
    async def on_slash_command_error(self, ctx: ApplicationCustomContext, exception):
        if isinstance(exception, (commands.MissingPermissions, commands.NotOwner, commands.MissingRole, commands.CheckFailure, commands.BadArgument, SubscriptionError)):
            return await ctx.send(content=f"{self.bot.emotes.error} {exception}")
        if isinstance(exception, Forbidden):
            return await ctx.send("The bot does not have access to send messages!")

        if await self.bot.is_owner(ctx.author):
            err_msg = f"{self.bot.emotes.error} There was an error executing this command.\n`{type(exception).__name__}: {exception}`"
        else:
            err_msg = f"{self.bot.emotes.error} There was an error executing this command."
        await ctx.send(err_msg)

        exc = ''.join(format_exception(type(exception), exception, exception.__traceback__))
        self.bot.log.error(f"Ignoring exception in command {ctx.application_command.name}:\n{exc}")
        error_str = str(exc).replace("\\", "\\\\")[:1900]
        channel = self.bot.get_channel(763351494685884446)
        if channel is not None:
            await channel.send(f"```python\nException in command {ctx.application_command.name}\n{error_str}\n```")

def setup(bot):
    bot.add_cog(ErrorListener(bot))