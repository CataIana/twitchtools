from discord.ext import commands
from traceback import format_exc, format_exception
from urllib3.exceptions import ProtocolError
from asyncio import TimeoutError

class ErrorListener(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    @commands.Cog.listener()
    async def on_error(self, event, *args, **kwargs):
        channel = self.bot.get_guild(749646865531928628).get_channel(763351494685884446)
        self.log.error(format_exc())
        await channel.send(f"```python\n{format_exc()[:1982]}\n```")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, exception):
        if isinstance(exception, (commands.DisabledCommand, commands.CommandOnCooldown, commands.MissingPermissions)): #Command errors/restrictions that owners override
            if ctx.author.id in [[ctx.cog.bot.owner_id] + list(ctx.cog.bot.owner_ids)]:
                await ctx.reinvoke()
                return
        if isinstance(exception, (ConnectionResetError, ProtocolError)):
            await self.bot.invoke(ctx)
            return
        if isinstance(exception, commands.DisabledCommand):
            await ctx.send(content=f'<:red_tick:809191812337369118> {ctx.command} has been disabled.')
            return
        if isinstance(exception, commands.CommandOnCooldown):
            retry_after = int(exception.retry_after) if int(exception.retry_after) != 0 else int(exception.retry_after)+1
            await ctx.send(content=f"<:red_tick:809191812337369118> Please try again after {retry_after} second{'' if retry_after == 1 else 's'}.")
            return
        if isinstance(exception, commands.BotMissingPermissions):
            await ctx.send(content=exception)
            return
        if isinstance(exception, commands.BadUnionArgument):
            await ctx.send(content="<:red_tick:809191812337369118> Unable to locate user")
            return
        if isinstance(exception, commands.ChannelNotFound):
            await ctx.send(content="<:red_tick:809191812337369118> Unable to locate channel")
            return
        if isinstance(exception, commands.MemberNotFound):
            await ctx.send(content="<:red_tick:809191812337369118> Unable to locate member")
            return
        if isinstance(exception, commands.NSFWChannelRequired):
            await ctx.send(content="<:red_tick:809191812337369118> This command can only be run in an NSFW channel! Get your horny ass in there")
            return
        if isinstance(exception, (commands.MissingRequiredArgument, commands.BadArgument)):
            await ctx.send(content=f"<:red_tick:809191812337369118> {exception}")
            return
        ignored = (commands.CommandNotFound, commands.CheckFailure, TimeoutError)
        if isinstance(exception, ignored): return
        
        exception = getattr(exception, 'original', exception)

        await ctx.send(content="<:red_tick:809191812337369118> There was an error executing this command.")

        exc = ''.join(format_exception(type(exception), exception, exception.__traceback__))
        self.bot.log.error(f"Ignoring exception in command {ctx.command}:\n{exc}")
        channel = self.bot.get_guild(749646865531928628).get_channel(763351494685884446)
        error_str = str(exc).replace("\\", "\\\\")[:1900]
        await channel.send(f"```python\nException in command {ctx.command}\n{error_str}\n```")

def setup(bot):
    bot.add_cog(ErrorListener(bot))