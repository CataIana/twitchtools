import asyncio
import sys
from collections import deque
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from os import getpid
from textwrap import shorten
from time import time
from types import BuiltinFunctionType, CoroutineType, FunctionType, MethodType
from typing import Callable, TypeVar

import disnake
import psutil
from disnake import Embed, Role
from disnake.ext import commands
from disnake.utils import utcnow
from munch import munchify

from main import TwitchCallBackBot
from twitchtools import ApplicationCustomContext, human_timedelta


class TimestampOptions(Enum):
    short_time = "t"  # 1:21 PM
    long_time = "T"  # 1:21:08 PM
    short_date = "d"  # 07/10/2021
    long_date = "D"  # July 10, 2021
    long_date_short_time = "f"  # July 10, 2021 1:21 PM
    long_date_with_day_of_week_and_short_time = "F"  # Saturday, July 10, 2021 1:21 PM
    relative = "R"  # 6 minutes ago


def DiscordTimezone(utc, format: TimestampOptions):
    return f"<t:{int(utc)}:{format.value}>"


T = TypeVar("T")


def has_manage_permissions() -> Callable[[T], T]:
    async def predicate(ctx: ApplicationCustomContext) -> bool:
        if not ctx.guild:
            raise commands.NoPrivateMessage

        # Bot owner override all permissions
        if await ctx.bot.is_owner(ctx.author):
            return True

        if ctx.author.guild_permissions.administrator:
            return True

        manager_role_id = await ctx.bot.db.get_manager_role(ctx.guild)
        manager_role = ctx.guild.get_role(manager_role_id)
        if manager_role:
            if manager_role in ctx.author.roles:
                return True

        raise commands.CheckFailure(
            "You do not have permission to run this command. Only server administrators or users with the manager role can run commands. If you believe this is a mistake, ask your admin about the `/managerrole` command")

    return commands.check(predicate)


def has_guild_permissions(owner_override: bool = False, **perms: bool) -> Callable[[T], T]:
    """Similar to :func:`.has_permissions`, but operates on guild wide
    permissions instead of the current channel permissions.
    If this check is called in a DM context, it will raise an
    exception, :exc:`.NoPrivateMessage`.
    .. versionadded:: 1.3
    """

    invalid = set(perms) - set(disnake.Permissions.VALID_FLAGS)
    if invalid:
        raise TypeError(f"Invalid permission(s): {', '.join(invalid)}")

    async def predicate(ctx: ApplicationCustomContext) -> bool:
        if not ctx.guild:
            raise commands.NoPrivateMessage

        if owner_override:
            if await ctx.bot.is_owner(ctx.author):
                return True

        permissions = ctx.author.guild_permissions
        missing = [perm for perm, value in perms.items(
        ) if getattr(permissions, perm) != value]

        if not missing:
            return True

        raise commands.MissingPermissions(missing)

    return commands.check(predicate)


class CommandsCog(commands.Cog):
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()

    @commands.Cog.listener()
    async def on_raw_interaction(self, interaction):
        await self.bot.wait_until_ready()
        if interaction["type"] != 2:
            return
        ctx = await self.bot.get_slash_context(interaction, cls=ApplicationCustomContext)
        await self.bot.application_invoke(ctx)

    @commands.Cog.listener()
    async def on_slash_command(self, ctx: ApplicationCustomContext):
        if ctx.application_command:
            self.bot.log.info(
                f"Handling slash command {ctx.application_command.qualified_name} for {ctx.author} in {ctx.guild.name}")
        else:
            self.bot.log.info(f"Attemped to run invalid slash command!")

    @commands.slash_command(description="Responds with the bots latency to discords servers")
    @has_manage_permissions()
    async def ping(self, ctx: ApplicationCustomContext):
        gateway = int(self.bot.latency*1000)
        # Message cannot be ephemeral for ping updates to show
        await ctx.send(f"Pong! `{gateway}ms` Gateway")

    @commands.slash_command(description="Owner Only: Reload the bot cogs and listeners")
    @commands.is_owner()
    async def reload(self, ctx: ApplicationCustomContext):
        cog_count = 0
        for ext_name in dict(self.bot.extensions).keys():
            cog_count += 1
            self.bot.reload_extension(ext_name)
        await ctx.send(f"{self.bot.emotes.success} Succesfully reloaded! Reloaded {cog_count} cogs!", ephemeral=True)

    @commands.slash_command(description="Owner Only: Run streamer catchup manually")
    @commands.is_owner()
    async def catchup(self, ctx: ApplicationCustomContext):
        await ctx.response.defer()
        await self.bot.twitch_catchup()
        await self.bot.youtube_catchup()
        self.bot.log.info("Finished manual catchup")
        await ctx.send(f"{self.bot.emotes.success} Finished catchup!", ephemeral=True)

    @commands.slash_command(description="Get various bot information such as memory usage and version")
    @has_manage_permissions()
    async def botstatus(self, ctx: ApplicationCustomContext):
        embed = Embed(title=f"{self.bot.user.name} Status",
                      colour=self.bot.colour, timestamp=utcnow())
        if self.bot.owner_id is None:
            owner_objs = [str(self.bot.get_user(user))
                          for user in self.bot.owner_ids]
            owners = ', '.join(owner_objs).rstrip(", ")
            is_plural = False
            if len(owner_objs) > 1:
                is_plural = True
        else:
            owners = await self.bot.fetch_user(self.bot.owner_id)
            is_plural = False
        callbacks = await self.bot.db.get_all_callbacks()
        alert_count = 0
        for data in callbacks.values():
            alert_count += len(data["alert_roles"].values())
        botinfo = f"**🏠 Servers:** {len(self.bot.guilds)}\n**🤖 Bot Creation Date:** {DiscordTimezone(int(self.bot.user.created_at.timestamp()), TimestampOptions.long_date_short_time)}\n**🕑 Uptime:** {human_timedelta(datetime.utcfromtimestamp(self.bot._uptime), suffix=False)}\n**⚙️ Cogs:** {len(self.bot.cogs)}\n**📈 Commands:** {len(self.bot.slash_commands)}\n**🏓 Latency:**  {int(self.bot.latency*1000)}ms\n**🕵️‍♀️ Owner{'s' if is_plural else ''}:** {owners}\n**<:Twitch:891703045908467763> Subscribed Streamers:** {len(callbacks.keys())}\n**<:notaggy:891702828756766730> Notification Count:** {alert_count}"
        embed.add_field(name="__Bot__", value=botinfo, inline=False)
        memory = psutil.virtual_memory()
        cpu_freq = psutil.cpu_freq()
        systeminfo = f"**<:python:879586023116529715> Python Version:** {sys.version.split()[0]}\n**<:discordpy:879586265014607893> Disnake Version:** {disnake.__version__}\n**🖥️ CPU:** {psutil.cpu_count()}x @{round((cpu_freq.max if cpu_freq.max != 0 else cpu_freq.current)/1000, 2)}GHz\n**<:microprocessor:879591544070488074> Process Memory Usage:** {psutil.Process(getpid()).memory_info().rss/1048576:.2f}MB\n**<:microprocessor:879591544070488074> System Memory Usage:** {memory.used/1048576:.2f}MB ({memory.percent}%) of {memory.total/1048576:.2f}MB"
        embed.add_field(name="__System__", value=systeminfo, inline=False)
        embed.set_author(name=self.bot.user.name,
                         icon_url=self.bot.user.display_avatar.with_size(128))
        embed.set_footer(text=f"Client ID: {self.bot.user.id}")
        await ctx.send(embed=embed)

    async def aeval(self, ctx: ApplicationCustomContext, code):
        code_split = ""
        code_length = len(code.split("\\n"))
        for count, line in enumerate(code.split("\\n"), 1):
            if count == code_length:
                code_split += f"    return {line}"
            else:
                code_split += f"    {line}\n"
        combined = f"async def __ex(self, ctx):\n{code_split}"
        exec(combined)
        return await locals()['__ex'](self, ctx)

    def remove_tokens(self, string: str) -> str:
        vars = [
            self.bot.token
        ]
        for var in vars:
            string = string.replace(var, "<Hidden>")
        return string

    async def eval_autocomplete(ctx: ApplicationCustomContext, com: str):
        if not await ctx.bot.is_owner(ctx.author):
            return ["You do not have permission to use this command"]
        self = ctx.application_command.cog
        com = com.split("await ", 1)[-1]  # Strip await
        try:
            com_split = '.'.join(com.split(".")[:-1])
            var_request = '.'.join(com.split(".")[-1:])
            if com_split == '':
                com_split = var_request
                var_request = ""
            resp = await self.aeval(ctx, com_split)
            if isinstance(resp, CoroutineType):
                resp = await resp
        except Exception as ex:
            return ["May want to keep typing...", "Exception: ", str(ex), com]
        else:
            if type(resp) == str:
                return [resp]
            if type(resp) == dict:
                resp = munchify(resp)

            attributes = []  # List of all attributes
            # get a list of all attributes and their values, along with all the functions in seperate lists
            for attr_name in dir(resp):
                try:
                    attr = getattr(resp, attr_name)
                except AttributeError:
                    pass
                if attr_name.startswith("_"):
                    continue  # Most methods/attributes starting with __ or _ are generally unwanted, skip them
                if type(attr) not in [MethodType, BuiltinFunctionType, FunctionType]:
                    if var_request:
                        if not str(attr_name).startswith(var_request):
                            continue
                    if isinstance(attr, (list, deque)):
                        attributes.append(shorten(com_split + "." + self.remove_tokens(
                            f"{str(attr_name)}: {type(attr).__name__.title()}[{type(attr[0]).__name__.title() if len(attr) != 0 else 'None'}] [{len(attr)}]"), width=100))
                    elif isinstance(attr, (dict, commands.core._CaseInsensitiveDict, Mapping)):
                        attributes.append(shorten(com_split + "." + self.remove_tokens(
                            f"{str(attr_name)}: {type(attr).__name__.title()}[{type(list(attr.keys())[0]).__name__ if len(attr) != 0 else 'None'}, {type(list(attr.values())[0]).__name__ if len(attr) != 0 else 'None'}] [{len(attr)}]"), width=100))
                    elif type(attr) == set:
                        attr_ = list(attr)
                        attributes.append(shorten(com_split + "." + self.remove_tokens(
                            f"{str(attr_name)}: {type(attr).__name__.title()}[{type(attr_[0]).__name__.title() if len(attr) != 0 else 'None'}] [{len(attr)}]"), width=100))
                    else:
                        b = com_split + "." + \
                            self.remove_tokens(
                                str(attr_name)) + ": {} [" + type(attr).__name__ + "]"
                        attributes.append(
                            b.format(str(attr)[:100-len(b)-5] + " [...]"))
                else:
                    if var_request:
                        if not str(attr_name).startswith(var_request):
                            continue
                    if asyncio.iscoroutinefunction(attr):
                        attributes.append(shorten(
                            com_split + "." + f"{str(attr_name)}: [async {type(attr).__name__}]", width=100))
                    else:
                        attributes.append(shorten(
                            com_split + "." + f"{str(attr_name)}: [{type(attr).__name__}]", width=100))
            return attributes[:25]

    @commands.slash_command(description="Evalute a string as a command")
    @commands.is_owner()
    async def eval(self, ctx: ApplicationCustomContext, command: str = commands.Param(autocomplete=eval_autocomplete), respond: bool = True):
        command = command.split(":")[0]
        show_all = False
        code_string = "```nim\n{}```"
        if command.startswith("`") and command.endswith("`"):
            command = command[1:][:-1]
        start = time()
        try:
            resp = await self.aeval(ctx, command)
            if isinstance(resp, CoroutineType):
                resp = await resp
        except Exception as ex:
            await ctx.send(content=f"Exception Occurred: `{type(ex).__name__}: {ex}`")
        else:
            finish = time()
            if respond:
                if type(resp) == str:
                    return await ctx.send(code_string.format(resp))

                attributes = {}  # Dict of all attributes
                methods = []  # Sync methods
                amethods = []  # Async methods
                # get a list of all attributes and their values, along with all the functions in seperate lists
                for attr_name in dir(resp):
                    try:
                        attr = getattr(resp, attr_name)
                    except AttributeError:
                        pass
                    if not show_all:
                        if attr_name.startswith("_"):
                            continue  # Most methods/attributes starting with __ or _ are generally unwanted, skip them
                    if type(attr) not in [MethodType, BuiltinFunctionType, FunctionType]:
                        if isinstance(attr, (list, deque)):
                            attributes[str(
                                attr_name)] = f"{type(attr).__name__.title()}[{type(attr[0]).__name__.title() if len(attr) != 0 else 'None'}] [{len(attr)}]"
                        elif isinstance(attr, (dict, commands.core._CaseInsensitiveDict, Mapping)):
                            attributes[str(
                                attr_name)] = f"{type(attr).__name__.title()}[{type(list(attr.keys())[0]).__name__ if len(attr) != 0 else 'None'}, {type(list(attr.values())[0]).__name__ if len(attr) != 0 else 'None'}] [{len(attr)}]"
                        elif type(attr) == set:
                            attr_ = list(attr)
                            attributes[str(
                                attr_name)] = f"{type(attr).__name__.title()}[{type(attr_[0]).__name__.title() if len(attr) != 0 else 'None'}] [{len(attr)}]"
                        else:
                            attributes[str(attr_name)
                                       ] = f"{attr} [{type(attr).__name__}]"
                    else:
                        if asyncio.iscoroutinefunction(attr):
                            amethods.append(attr_name)
                        else:
                            methods.append(attr_name)

                # Form the long ass string of everything
                return_string = []
                if type(resp) != list:
                    stred = str(resp)
                else:
                    stred = '\n'.join([str(r) for r in resp])
                # List return type, it's str value
                return_string += [f"Type: {type(resp).__name__}",
                                  f"String: {stred}"]
                if attributes != {}:
                    return_string += ["", "Attributes: "]
                    return_string += [self.remove_tokens(
                        f"{x+': ':20s}{shorten(y, width=(106-len(x)))}") for x, y in attributes.items()]

                if methods != []:
                    return_string.append("\nMethods:")
                    return_string.append(
                        ', '.join([method for method in methods]).rstrip(", "))

                if amethods != []:
                    return_string.append("\nAsync/Awaitable Methods:")
                    return_string.append(
                        ', '.join([method for method in amethods]).rstrip(", "))

                return_string.append(
                    f"\nTook {((finish-start)*1000):2f}ms to process eval")

                d_str = ""
                for x in return_string:
                    if len(d_str + f"{x.rstrip(', ')}\n") < 1990:
                        d_str += f"{x.rstrip(', ')}\n"
                    else:
                        if len(code_string.format(d_str)) > 2000:
                            while d_str != "":
                                await ctx.send(code_string.format(d_str[:1990]))
                                d_str = d_str[1990:]
                        else:
                            await ctx.send(code_string.format(d_str))
                        d_str = f"{x.rstrip(', ')}\n"
                if d_str != "":
                    try:
                        await ctx.send(code_string.format(d_str))
                    except disnake.errors.NotFound:
                        pass

    @commands.slash_command(name="managerrole")
    @has_guild_permissions(owner_override=True, administrator=True)
    async def manager_role(self, ctx: ApplicationCustomContext):
        pass

    @manager_role.sub_command(name="get", description="Get what role is set as the manager role")
    async def manager_get(self, ctx: ApplicationCustomContext):
        role_id = await self.bot.db.get_manager_role(ctx.guild)
        if not role_id:
            return await ctx.send(f"No manager role is set for **{ctx.guild.name}**")
        role = ctx.guild.get_role(role_id)
        if not role:
            return await ctx.send(f"No manager role is set for **{ctx.guild.name}**")
        await ctx.send(f"The manager role for **{ctx.guild.name}** is **{role.name}**")

    @manager_role.sub_command(name="set", description="Define a manager role that allows a role to use the bot commands")
    async def manager_set(self, ctx: ApplicationCustomContext, role: Role):
        await self.bot.db.write_manager_role(ctx.guild, role)
        await ctx.send(f"Set the manager role for **{ctx.guild.name}** to **{role.name}**")

    @manager_role.sub_command(name="remove", description="Remove the manager role if it has been set")
    async def manager_remove(self, ctx: ApplicationCustomContext):
        if not await self.bot.db.get_manager_role(ctx.guild):
            return await ctx.send(f"No manager role is set for **{ctx.guild.name}**")
        await self.bot.db.delete_manager_role(ctx.guild)
        await ctx.send(f"Removed the manager role for **{ctx.guild.name}**")

    @commands.slash_command(description="Owner Only: Test if callback is functioning correctly")
    @commands.is_owner()
    async def testcallback(self, ctx: ApplicationCustomContext):
        await ctx.response.defer()
        try:
            r = await self.bot.tapi._request(f"{self.bot.tapi.callback_url}/callback/_callbacktest", method="POST")
        except asyncio.TimeoutError:
            return await ctx.send(f"{self.bot.emotes.error} Callback test failed. Server timed out")
        if r.status == 204:
            await ctx.send(f"{self.bot.emotes.success} Callback Test Successful. Returned expected HTTP status code 204")
        else:
            await ctx.send(f"{self.bot.emotes.error} Callback test failed. Expected HTTP status code 204 but got {r.status}")


def setup(bot):
    bot.add_cog(CommandsCog(bot))
