import disnake
from disnake import Embed, TextChannel, Role
from disnake.ext import commands, tasks
from disnake.utils import utcnow
import json
import asyncio
from datetime import datetime
from time import strftime, localtime, time
from types import BuiltinFunctionType, FunctionType, MethodType
from json.decoder import JSONDecodeError
from random import choice
from string import ascii_letters
import aiofiles
from os import getpid
import sys
import psutil
from textwrap import shorten
from enum import Enum
from main import TwitchCallBackBot
from twitchtools import SubscriptionType, User, PartialUser, Stream, ApplicationCustomContext
from twitchtools import AlertOrigin
from twitchtools.exceptions import SubscriptionError
from typing import Union
from types import CoroutineType
from collections.abc import Mapping
from collections import deque


class TimezoneOptions(Enum):
    short_date = "d" #07/10/2021
    month_day_year_time = "f" #July 10, 2021 1:21 PM
    time = "t" #1:21 PM
    short_date2 = "D" #July 10, 2021
    full_date_time = "F" #Saturday, July 10, 2021 1:21 PM
    long_ago = "R" #6 minutes ago
    long_time = "T" #1:21:08 PM

def DiscordTimezone(utc, format: TimezoneOptions):
    return f"<t:{int(utc)}:{format.value}>"

class pretty_time:
    def __init__(self, unix, duration=False):
        unix = float(unix)
        if not duration:
            self.unix_diff = time() - unix
        else:
            self.unix_diff = unix
        self.unix = unix
        self.years = int(str(self.unix_diff // 31536000).split('.')[0])
        self.days = int(str(self.unix_diff // 86400 % 365).split('.')[0])
        self.hours = int(str(self.unix_diff // 3600 % 24).split('.')[0])
        self.minutes = int(str(self.unix_diff // 60 % 60).split('.')[0])
        self.seconds = int(str(self.unix_diff % 60).split('.')[0])
        timezone_datetime = datetime.fromtimestamp(unix)
        self.datetime = timezone_datetime.strftime('%I:%M:%S %p %Y-%m-%d %Z')

        self.dict = {"days": self.days, "hours": self.hours, "minutes": self.minutes, "seconds": self.seconds, "datetime": self.datetime}

        full = []
        if self.years != 0:
            full.append(f"{self.years} {'year' if self.years == 1 else 'years'}")
        if self.days != 0:
            full.append(f"{self.days} {'day' if self.days == 1 else 'days'}")
        if self.hours != 0:
            full.append(f"{self.hours} {'hour' if self.hours == 1 else 'hours'}")
        if self.minutes != 0:
            full.append(f"{self.minutes} {'minute' if self.minutes == 1 else 'minutes'}")
        if self.seconds != 0:
            full.append(f"{self.seconds} {'second' if self.seconds == 1 else 'seconds'}")
        full = (', '.join(full[0:-1]) + " and " + ' '.join(full[-1:])) if len(full) > 1 else ', '.join(full)
        self.prettify = full

from typing import Callable, TypeVar
T = TypeVar("T")

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

        permissions = ctx.author.guild_permissions  # type: ignore
        missing = [perm for perm, value in perms.items() if getattr(permissions, perm) != value]

        if not missing:
            return True

        raise commands.MissingPermissions(missing)

    return commands.check(predicate)

class RecieverCommands(commands.Cog):
    from twitchtools.files import get_callbacks, write_callbacks, get_title_callbacks, write_title_callbacks
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()
        self.backup_checks.start()

    def cog_unload(self):
        self.backup_checks.cancel()
        pass

    @tasks.loop(seconds=1800)
    async def backup_checks(self):
        await self.bot.catchup_streamers()
        self.bot.log.info("Ran streamer catchup")

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
            self.bot.log.info(f"Handling slash command {ctx.application_command.name} for {ctx.author} in {ctx.guild.name}")
        else:
            self.bot.log.info(f"Attemped to run invalid slash command!")

    @commands.slash_command(description="Responds with the bots latency to discords servers")
    @has_guild_permissions(owner_override=True, manage_guild=True)
    async def ping(self, ctx: ApplicationCustomContext):
        gateway = int(self.bot.latency*1000)
        await ctx.send(f"Pong! `{gateway}ms` Gateway") #Message cannot be ephemeral for ping updates to show

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
        self.bot.log.info("Manually Running streamer catchup...")
        await self.bot.catchup_streamers()
        self.bot.log.info("Finished streamer catchup")
        await ctx.send(f"{self.bot.emotes.success} Finished catchup!", ephemeral=True)

    @commands.slash_command(description="Get various bot information such as memory usage and version")
    @has_guild_permissions(owner_override=True, manage_guild=True)
    async def botstatus(self, ctx: ApplicationCustomContext):
        p = pretty_time(self.bot._uptime)
        embed = Embed(title=f"{self.bot.user.name} Status", colour=self.bot.colour, timestamp=utcnow())
        if self.bot.owner_id is None:
            owner_objs = [str(self.bot.get_user(user)) for user in self.bot.owner_ids]
            owners = ', '.join(owner_objs).rstrip(", ")
            is_plural = False
            if len(owner_objs) > 1:
                is_plural = True
        else:
            owners = await self.bot.fetch_user(self.bot.owner_id)
            is_plural = False
        callbacks = await self.get_callbacks()
        alert_count = 0
        for data in callbacks.values():
            alert_count += len(data["alert_roles"].values())
        botinfo = f"**🏠 Servers:** {len(self.bot.guilds)}\n**🤖 Bot Creation Date:** {DiscordTimezone(int(self.bot.user.created_at.timestamp()), TimezoneOptions.month_day_year_time)}\n**🕑 Uptime:** {p.prettify}\n**⚙️ Cogs:** {len(self.bot.cogs)}\n**📈 Commands:** {len(self.bot.slash_commands)}\n**🏓 Latency:**  {int(self.bot.latency*1000)}ms\n**🕵️‍♀️ Owner{'s' if is_plural else ''}:** {owners}\n**<:Twitch:891703045908467763> Subscribed Streamers:** {len(callbacks.keys())}\n**<:notaggy:891702828756766730> Notification Count:** {alert_count}"
        embed.add_field(name="__Bot__", value=botinfo, inline=False)
        memory = psutil.virtual_memory()
        cpu_freq = psutil.cpu_freq()
        systeminfo = f"**<:python:879586023116529715> Python Version:** {sys.version.split()[0]}\n**<:discordpy:879586265014607893> Disnake Version:** {disnake.__version__}\n**🖥️ CPU:** {psutil.cpu_count()}x @{round((cpu_freq.max if cpu_freq.max != 0 else cpu_freq.current)/1000, 2)}GHz\n**<:microprocessor:879591544070488074> Process Memory Usage:** {psutil.Process(getpid()).memory_info().rss/1048576:.2f}MB\n**<:microprocessor:879591544070488074> System Memory Usage:** {memory.used/1048576:.2f}MB ({memory.percent}%) of {memory.total/1048576:.2f}MB"
        embed.add_field(name="__System__", value=systeminfo, inline=False)
        embed.set_author(name=self.bot.user.name, icon_url=self.bot.user.display_avatar.with_size(128))
        embed.set_footer(text=f"Client ID: {self.bot.user.id}")
        await ctx.send(embed=embed)

    @commands.slash_command(description="Get how long the bot has been running")
    @has_guild_permissions(owner_override=True, manage_guild=True)
    async def uptime(self, ctx: ApplicationCustomContext):
        epoch = time() - self.bot._uptime
        conv = {
            "days": str(epoch // 86400).split('.')[0],
            "hours": str(epoch // 3600 % 24).split('.')[0],
            "minutes": str(epoch // 60 % 60).split('.')[0],
            "seconds": str(epoch % 60).split('.')[0],
            "full": strftime('%Y-%m-%d %I:%M:%S %p %Z', localtime(self.bot._uptime))
        }
        description = f"{conv['days']} {'day' if conv['days'] == '1' else 'days'}, {conv['hours']} {'hour' if conv['hours'] == '1' else 'hours'}, {conv['minutes']} {'minute' if conv['minutes'] == '1' else 'minutes'} and {conv['seconds']} {'second' if conv['seconds'] == '1' else 'seconds'}"
        embed = Embed(title="Uptime", description=description,
                            color=self.bot.colour, timestamp=datetime.utcnow())
        embed.set_footer(
            text=f"ID: {ctx.guild.id} | Bot started at {conv['full']}")
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
            self.bot.token,
            str(self.bot.auth)
        ]
        for var in vars:
            string = string.replace(var, "<Hidden>")
        return string

    @commands.slash_command(description="Evalute a string as a command")
    @commands.is_owner()
    async def eval(self, ctx: ApplicationCustomContext, *, com: str, respond: bool = True):
        if isinstance(ctx, commands.Context):
            respond = False if ctx.invoked_with == "evalr" else True
        show_all = False
        if isinstance(ctx, commands.Context):
            show_all = True if ctx.invoked_with == "evala" else False
        code_string = "```nim\n{}```"
        if com.startswith("`") and com.endswith("`"):
            com = com[1:][:-1]
        start = time()
        try:
            resp = await self.aeval(ctx, com)
            if isinstance(resp, CoroutineType):
                resp = await resp
        except Exception as ex:
            await ctx.send(content=f"Exception Occurred: `{type(ex).__name__}: {ex}`")
        else:
            finish = time()
            if respond:
                if type(resp) == str:
                    return await ctx.send(code_string.format(resp))

                attributes = {} #Dict of all attributes
                methods = [] #Sync methods
                amethods = [] #Async methods
                #get a list of all attributes and their values, along with all the functions in seperate lists
                for attr_name in dir(resp):
                    try:
                        attr = getattr(resp, attr_name)
                    except AttributeError:
                        pass
                    if not show_all:
                        if attr_name.startswith("_"):
                            continue #Most methods/attributes starting with __ or _ are generally unwanted, skip them
                    if type(attr) not in [MethodType, BuiltinFunctionType, FunctionType]:
                        if isinstance(attr, (list, deque)):
                            attributes[str(attr_name)] = f"{type(attr).__name__.title()}[{type(attr[0]).__name__.title() if len(attr) != 0 else 'None'}] [{len(attr)}]"
                        elif isinstance(attr, (dict, commands.core._CaseInsensitiveDict, Mapping)):
                            attributes[str(attr_name)] = f"{type(attr).__name__.title()}[{type(list(attr.keys())[0]).__name__ if len(attr) != 0 else 'None'}, {type(list(attr.values())[0]).__name__ if len(attr) != 0 else 'None'}] [{len(attr)}]"
                        elif type(attr) == set:
                            attr_ = list(attr)
                            attributes[str(attr_name)] = f"{type(attr).__name__.title()}[{type(attr_[0]).__name__.title() if len(attr) != 0 else 'None'}] [{len(attr)}]"
                        else:
                            attributes[str(attr_name)] = f"{attr} [{type(attr).__name__}]"
                    else:
                        if asyncio.iscoroutinefunction(attr):
                            amethods.append(attr_name)
                        else:
                            methods.append(attr_name)

                #Form the long ass string of everything
                return_string = []
                if type(resp) != list:
                    stred = str(resp)
                else:
                    stred = '\n'.join([str(r) for r in resp])
                return_string += [f"Type: {type(resp).__name__}", f"String: {stred}"] #List return type, it's str value
                if attributes != {}:
                    return_string += ["", "Attributes: "]
                    return_string += [self.remove_tokens(f"{x+': ':20s}{shorten(y, width=(106-len(x)))}") for x, y in attributes.items()]

                if methods != []:
                    return_string.append("\nMethods:")
                    return_string.append(', '.join([method for method in methods]).rstrip(", "))

                if amethods != []:
                    return_string.append("\nAsync/Awaitable Methods:")
                    return_string.append(', '.join([method for method in amethods]).rstrip(", "))

                return_string.append(f"\nTook {((finish-start)*1000):2f}ms to process eval")

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

    async def check_streamer(self, username) -> User:
        return await self.bot.api.get_user(user_login=username)

    async def check_channel_permissions(self, ctx: ApplicationCustomContext, channel: Union[TextChannel, int]):
        if isinstance(channel, int): channel = self.bot.get_channel(channel)
        else: channel = self.bot.get_channel(channel.id)
        if not isinstance(channel, disnake.TextChannel):
            raise commands.BadArgument(f"Channel {channel.mention} is not a text channel!")

        perms = {"view_channel": True, "read_message_history": True, "send_messages": True}
        permissions = channel.permissions_for(ctx.guild.me)

        missing = [perm for perm, value in perms.items() if getattr(permissions, perm) != value]
        if not missing:
            return True

        raise commands.BotMissingPermissions(missing)

    @commands.slash_command(name="addstreamer", description="Add live alerts for the provided streamer")
    @has_guild_permissions(owner_override=True, manage_guild=True)
    async def addstreamer(self,
                        ctx: ApplicationCustomContext,
                        streamer_username: str,
                        alert_mode: commands.option_enum({
                            "Mode 0 - Creates a temporary channel when the streamer is live": 0,
                            "Mode 2 - Updates a persistent status channel when the streamer goes live and offline": 2
                        }),
                        notification_channel: TextChannel = commands.Param(description="The channel for notifications to be sent in"),
                        alert_role: Role = commands.Param(default=None, description="The role to be pinged for alerts"),
                        status_channel: TextChannel = commands.Param(default=None, description="Only for Mode 2: The channel that is renamed when streamer goes live/offline"),
                        title_phrase: str = commands.Param(default=None, description="Alerts are only sent if the phrase provided is in the title of the stream. CASE INSENSITIVE"),
                        disable_channel_rename: bool = commands.Param(default=False, description="Only for Mode 2: Disables renaming of channel when going live/offline.")
        ):
        # Run checks on all the supplied arguments
        streamer = await self.check_streamer(username=streamer_username)
        if not streamer:
            raise commands.BadArgument(f"Could not find twitch user {streamer_username}!")
        await self.check_channel_permissions(ctx, channel=notification_channel)
        if status_channel is not None:
            await self.check_channel_permissions(ctx, channel=status_channel)

        if isinstance(notification_channel, int): notification_channel = self.bot.get_channel(notification_channel)
        if isinstance(status_channel, int): status_channel = self.bot.get_channel(status_channel)
        
        if alert_mode == 2 and status_channel is None:
            raise commands.BadArgument(f"Alert Mode 2 requires a status channel!")

        #Checks done

        #Create file structure and subscriptions if necessary
        callbacks = await self.get_callbacks()
        
        
        make_subscriptions = False
        if streamer.username not in callbacks.keys():
            make_subscriptions = True
            callbacks[streamer.username] = {"channel_id": streamer.id, "secret": await random_string_generator(21), "alert_roles": {}}

        callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)] = {"mode": alert_mode, "notif_channel_id": notification_channel.id}
        if alert_role == None:
            callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["role_id"] = None
        elif alert_role == ctx.guild.default_role:
            callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["role_id"] = "everyone"
        else:
            callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["role_id"] = alert_role.id
        if alert_mode == 2:
            callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["channel_id"] = status_channel.id
        if title_phrase:
            callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["title_phrase"] = title_phrase.lower()
        if disable_channel_rename and alert_mode == 2:
            callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["disable_channel_rename"] = disable_channel_rename

        await self.write_callbacks(callbacks)

        if make_subscriptions:
            await ctx.response.defer()
            try:
                sub1 = await self.bot.api.create_subscription(SubscriptionType.STREAM_ONLINE, streamer=streamer, secret=callbacks[streamer.username]["secret"])
                callbacks[streamer.username]["online_id"] = sub1.id
                sub2 = await self.bot.api.create_subscription(SubscriptionType.STREAM_OFFLINE, streamer=streamer, secret=callbacks[streamer.username]["secret"])
                callbacks[streamer.username]["offline_id"] = sub2.id
                if title_phrase:
                    sub3 = await self.bot.api.create_subscription(SubscriptionType.CHANNEL_UPDATE, streamer=streamer, secret=callbacks[streamer.username]["secret"], _type="phrasecheck")
                    callbacks[streamer.username]["title_id"] = sub3.id
            except SubscriptionError as e:
                if title_phrase:
                    try:
                        await self.bot.api.delete_subscription(callbacks[streamer.username]["title_id"])
                    except KeyError:
                        pass
                await self.callback_deletion(ctx, streamer.username, config_file="callbacks.json")
                raise SubscriptionError(str(e))

        await self.write_callbacks(callbacks)

        #Run catchup on streamer immediately
        stream_status = await self.bot.api.get_stream(streamer.username, origin=AlertOrigin.catchup)
        if stream_status is None:
            if status_channel is not None and not disable_channel_rename:
                await status_channel.edit(name="stream-offline")
            self.bot.queue.put_nowait(streamer)
            #self.bot.dispatch("streamer_offline", streamer)
        else:
            self.bot.queue.put_nowait(stream_status)
            #self.bot.dispatch("streamer_online", stream_status)

        embed = Embed(title="Successfully added new streamer", color=self.bot.colour)
        embed.add_field(name="Streamer", value=streamer.username, inline=True)
        embed.add_field(name="Notification Channel", value=notification_channel.mention, inline=True)
        embed.add_field(name="Alert Role", value=alert_role, inline=True)
        embed.add_field(name="Alert Mode", value=alert_mode, inline=True)
        if alert_mode == 2:
            embed.add_field(name="Status Channel", value=status_channel.mention, inline=True)
            if disable_channel_rename:
                embed.add_field(name="Status Channel Rename", value="Disabled", inline=True)
        if title_phrase:
            embed.add_field(name="Title Alert Phrase", value=title_phrase, inline=True)
        await ctx.send(embed=embed)

    @commands.slash_command(description="List all the active streamer alerts setup in this server")
    @has_guild_permissions(owner_override=True, manage_guild=True)
    async def liststreamers(self, ctx: ApplicationCustomContext):
        callbacks = await self.get_callbacks()

        uwu = f"```nim\n{'Channel':15s} {'Alert Role':18s} {'Alert Channel':15s} {'Alert Mode':12s} {'Disable Channel Rename':22s} {'Title Phrase':20s}\n"
        for x, y in callbacks.items():
            if str(ctx.guild.id) in y["alert_roles"].keys():
                info = y["alert_roles"][str(ctx.guild.id)]
                alert_role = info.get("role_id", None)
                if alert_role is None:
                    alert_role = "<No Alert Role>"
                elif alert_role == "everyone":
                    alert_role == "@everyone"
                else:
                    try:
                        alert_role: Union[disnake.Role, None] = ctx.guild.get_role(int(alert_role))
                    except ValueError:
                        alert_role = ""
                    else:
                        if alert_role is not None:
                            alert_role = alert_role.name
                        else:
                            alert_role = "@deleted-role"

                channel_override = info.get("notif_channel_id", None)
                channel_override: Union[disnake.TextChannel, None] = ctx.guild.get_channel(channel_override)
                if channel_override is not None:
                    channel_override = "#" + channel_override.name
                else:
                    channel_override = ""

                if len(uwu + f"{x:15s} {alert_role:18s} {channel_override:15s} {str(info.get('mode', 2)):12s} {str(info.get('disable_channel_rename', False)):22s} {info.get('title_phrase', ''):20s}\n") > 1800:
                    uwu += "```"
                    await ctx.send(uwu)
                    uwu = "```nim\n"
                uwu += f"{x:15s} {alert_role:18s} {channel_override:15s} {str(info.get('mode', 2)):12s} {str(info.get('disable_channel_rename', False)):22s} {info.get('title_phrase', ''):20s}\n"
        uwu += "```"
        await ctx.send(uwu)

    @commands.slash_command(description="List all the active title change alerts setup in this server")
    @has_guild_permissions(owner_override=True, manage_guild=True)
    async def listtitlechanges(self, ctx: ApplicationCustomContext):
        title_callbacks = await self.get_title_callbacks()
        uwu = f"```nim\n{'Channel':15s} {'Alert Role':35s} {'Alert Channel':18s}\n"
        for x, y in title_callbacks.items():
            if str(ctx.guild.id) in y["alert_roles"].keys():
                info = y["alert_roles"][str(ctx.guild.id)]
                alert_role = info.get("role_id", "")
                if alert_role is None:
                    alert_role = "<No Alert Role>"
                else:
                    try:
                        int(alert_role)
                    except ValueError:
                        pass
                    else:
                        alert_role: Union[disnake.Role, None] = ctx.guild.get_role(alert_role)
                        if alert_role is not None:
                            alert_role = alert_role.name
                        else:
                            alert_role = ""

                alert_channel = info.get("notif_channel_id", None)
                alert_channel: Union[disnake.TextChannel, None] = ctx.guild.get_channel(alert_channel)
                if alert_channel is not None:
                    alert_channel = "#" + alert_channel.name
                else:
                    alert_channel = ""

                if len(uwu + f"{x:15s} {alert_role:35s} {alert_channel:18s}\n") > 1800:
                    uwu += "```"
                    await ctx.send(uwu)
                    uwu = "```nim\n"
                uwu += f"{x:15s} {alert_role:35s} {alert_channel:18s}\n"
        uwu += "```"
        await ctx.send(uwu)

    @commands.slash_command(description="Add title change alerts for the provided streamer")
    @has_guild_permissions(owner_override=True, manage_guild=True)
    async def addtitlechange(self,
                            ctx: ApplicationCustomContext,
                            streamer_username: str,
                            notification_channel: TextChannel,
                            alert_role: Role = None
        ):
        # Run checks on all the supplied arguments
        streamer = await self.check_streamer(username=streamer_username)
        if not streamer:
            raise commands.BadArgument(f"Could not find twitch user {streamer_username}!")
        await self.check_channel_permissions(ctx, channel=notification_channel)

        #Checks done
        if isinstance(notification_channel, int): notification_channel = self.bot.get_channel(notification_channel)

        #Create file structure and subscriptions if necessary
        title_callbacks = await self.get_title_callbacks()
        
        make_subscriptions = False
        if streamer.username not in title_callbacks.keys():
            make_subscriptions = True
            title_callbacks[streamer.username] = {"channel_id": streamer.id, "secret": await random_string_generator(21), "alert_roles": {}}
            
        title_callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)] = {"notif_channel_id": notification_channel.id}
        if alert_role == None:
            title_callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["role_id"] = None
        elif alert_role == ctx.guild.default_role:
            title_callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["role_id"] = "everyone"
        else:
            title_callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["role_id"] = alert_role.id

        await self.write_title_callbacks(title_callbacks)

        if make_subscriptions:
            await ctx.response.defer()
            try:
                sub = await self.bot.api.create_subscription(SubscriptionType.CHANNEL_UPDATE, streamer=streamer, _type="titlecallback", secret=title_callbacks[streamer.username]["secret"])
            except SubscriptionError as e:
                await self.callback_deletion(ctx, streamer.username, config_file="title_callbacks.json", _type="title")
                raise SubscriptionError(str(e))
            title_callbacks[streamer.username]["subscription_id"] = sub.id

        await self.write_title_callbacks(title_callbacks)

        embed = Embed(title="Successfully added new title change alert", color=self.bot.colour)
        embed.add_field(name="Streamer", value=streamer.username, inline=True)
        embed.add_field(name="Notification Channel", value=notification_channel.mention, inline=True)
        embed.add_field(name="Alert Role", value=alert_role, inline=True)
        await ctx.send(embed=embed)

    @commands.slash_command()
    @has_guild_permissions(owner_override=True, manage_guild=True)
    async def delstreamer(self, ctx: ApplicationCustomContext, streamer: str):
        """
        Remove live alerts for a streamer
        """
        await self.callback_deletion(ctx, streamer.lower(), config_file="callbacks.json", _type="status")
        await ctx.send(f"{self.bot.emotes.success} Deleted live alerts for {streamer}")

    @commands.slash_command()
    @has_guild_permissions(owner_override=True, manage_guild=True)
    async def deltitlechange(self, ctx: ApplicationCustomContext, streamer: str):
        """
        Remove title change alerts for a streamer
        """
        await self.callback_deletion(ctx, streamer.lower(), config_file="title_callbacks.json", _type="title")
        await ctx.send(f"{self.bot.emotes.success} Deleted title change alert for {streamer}")

    async def callback_deletion(self, ctx: ApplicationCustomContext, streamer, config_file, _type="status"):
        try:
            async with aiofiles.open(f"config/{config_file}") as f:
                callbacks = json.loads(await f.read())
        except FileNotFoundError:
            callbacks = {}
        except JSONDecodeError:
            callbacks = {}
        try:
            del callbacks[streamer]["alert_roles"][str(ctx.guild.id)]
        except KeyError:
            raise commands.BadArgument("Streamer not found for server")
        if callbacks[streamer]["alert_roles"] == {}:
            self.bot.log.info(f"Streamer {streamer} has no more alerts, purging")
            try:
                if _type == "title":
                    await self.bot.api.delete_subscription(callbacks[streamer]['subscription_id'])
                elif _type == "status":
                    await self.bot.api.delete_subscription(callbacks[streamer]['offline_id'])
                    await self.bot.api.delete_subscription(callbacks[streamer]['online_id'])
                    if callbacks[streamer].get("title_id", None):
                        await self.bot.api.delete_subscription(callbacks[streamer]['title_id'])
            except KeyError:
                pass
            del callbacks[streamer]
        async with aiofiles.open(f"config/{config_file}", "w") as f:
            await f.write(json.dumps(callbacks, indent=4))

    @commands.slash_command(description="Owner Only: Test if callback is functioning correctly")
    @commands.is_owner()
    async def testcallback(self, ctx: ApplicationCustomContext):
        await ctx.response.defer()
        #This is just a shitty quick implementation. The web server should always return a status code 204 since no streamer should ever be named _callbacktest
        try:
            r = await self.bot.api._request(f"{self.bot.api.callback_url}/callback/_callbacktest", method="POST")
        except asyncio.TimeoutError:
            return await ctx.send(f"{self.bot.emotes.error} Callback test failed. Server timed out")
        if r.status == 204:
            await ctx.send(f"{self.bot.emotes.success} Callback Test Successful. Returned expected HTTP status code 204")
        else:
            await ctx.send(f"{self.bot.emotes.error} Callback test failed. Expected HTTP status code 204 but got {r.status}")


    @commands.slash_command(description="Owner Only: Resubscribe every setup callback. Useful for domain changes")
    @commands.is_owner()
    async def resubscribe(self, ctx: ApplicationCustomContext):
        self.bot.log.info("Running live alert resubscribe")
        await ctx.response.defer()
        callbacks = await self.get_callbacks()
        for streamer, data in callbacks.items():
            await asyncio.sleep(0.2)
            if data.get("online_id", None) is not None:
                await self.bot.api.delete_subscription(data["online_id"])
            rj1 = await self.bot.api.create_subscription(SubscriptionType.STREAM_ONLINE, streamer=PartialUser(data["channel_id"], streamer, streamer), secret=data["secret"])
            await asyncio.sleep(0.2)
            callbacks[streamer]["online_id"] = rj1.id
            if data.get("offline_id", None) is not None:
                await self.bot.api.delete_subscription(data["offline_id"])
            rj2 = await self.bot.api.create_subscription(SubscriptionType.STREAM_OFFLINE, streamer=PartialUser(data["channel_id"], streamer, streamer), secret=data["secret"])
            callbacks[streamer]["offline_id"] = rj2.id


            add_title = any([a for a in data["alert_roles"].values() if a.get("title_phrase", None) is not None])

            if add_title:
                if data.get("title_id", None) is not None:
                    await self.bot.api.delete_subscription(data["title_id"])
                rj3 = await self.bot.api.create_subscription(SubscriptionType.CHANNEL_UPDATE, streamer=PartialUser(data["channel_id"], streamer, streamer), secret=data["secret"], _type="phrasecheck")
                callbacks[streamer]["title_id"] = rj3.id
        await self.write_callbacks(callbacks)

        self.bot.log.info("Running title resubscribe")
        title_callbacks = await self.get_title_callbacks()
        for streamer, data in title_callbacks.items():
            await asyncio.sleep(0.2)
            if data.get("subscription_id", None) is not None:
                await self.bot.api.delete_subscription(data["subscription_id"])
            sub = await self.bot.api.create_subscription(SubscriptionType.CHANNEL_UPDATE, streamer=PartialUser(data["channel_id"], streamer, streamer), secret=data["secret"])
            await asyncio.sleep(0.2)
            title_callbacks[streamer]["subscription_id"] = sub.id
        await self.write_title_callbacks(title_callbacks)
        await ctx.send(f"{self.bot.emotes.success} Recreated all subscriptions!")
                


            
async def random_string_generator(str_size):
    return "".join(choice(ascii_letters) for _ in range(str_size))


def setup(bot):
    bot.add_cog(RecieverCommands(bot))