from discord.ext import commands
import inspect
from types import BuiltinFunctionType, FunctionType, MethodType

class RecieverCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    @commands.command()
    @commands.is_owner()
    async def eval(self, ctx, *, com):
        code_string = "```\n{}```"
        if com.startswith("await "):
            com = com.lstrip("await ")
        try:
            #resp = eval(com, {"__builtins__": {}, "self": self, "ctx": ctx}, {})
            resp = eval(com)
            if inspect.isawaitable(resp):
                resp = await resp
        except Exception as ex:
            await ctx.send(content=f"`{ex}`")
        else:
            d = {}
            for att in dir(resp):
                attr = getattr(resp, att)
                if not att.startswith("__") and type(attr) not in [MethodType, BuiltinFunctionType, FunctionType]:
                    d[str(att)] = f"{attr} [{type(attr).__name__}]"
            if d == {}:
                d["str"] = str(resp)
            d_str = ""
            for x, y in d.items():
                if len(d_str + f"{x}:    {y}\n") < 1990:
                    d_str += f"{x}:    {y}\n"
                else:
                    await ctx.send(content=code_string.format(d_str))
                    d_str = ""
                    if len(d_str + f"{x}:    {y}\n") < 1990:
                        d_str += f"{x}:    {y}\n"
            if d_str != "":
                await ctx.send(content=code_string.format(d_str))