import discord
from discord.ext import commands, tasks
from discord.utils import utcnow, snowflake_time
from dislash import application_commands
from dislash import Option, OptionType, OptionChoice, SlashInteraction, MessageInteraction, ContextMenuInteraction
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
from twitchtools import SubscriptionType, User, PartialUser, Stream
from twitchtools.exceptions import SubscriptionError
from twitchtools.interaction_client import CustomSlashInteraction, CustomContextMenuInteraction, CustomMessageInteraction
from typing import Union


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

class RecieverCommands(commands.Cog):
    from twitchtools.files import get_callbacks, write_callbacks, get_title_callbacks, write_title_callbacks
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()
        self.bot.help_command = None
        self.backup_checks.start()

    def cog_unload(self):
        self.backup_checks.cancel()
        pass

    @tasks.loop(seconds=1800)
    async def backup_checks(self):
        self.bot.log.info("Running streamer catchup...")
        await self.bot.catchup_streamers()
        self.bot.log.info("Finished streamer catchup")

    @commands.Cog.listener()
    async def on_dislash_interaction(self, payload: dict):
        await self.bot.wait_until_ready()
        _type = payload.get("type", 1)
        c = None
        if _type == 2:
            data_type = payload.get("data", {}).get("type", 1)
            if data_type == 1:
                c = self.get_custom_slash_context(CustomSlashInteraction)
            elif data_type in (2, 3):
                c = self.get_custom_slash_context(CustomContextMenuInteraction)
        elif _type == 3:
            c = self.get_custom_slash_context(CustomMessageInteraction)
        ctx = await self.bot.slash.get_context(payload, cls=c)
        await self.bot.slash.invoke(ctx)

    def get_custom_slash_context(self, base: Union[SlashInteraction, MessageInteraction, ContextMenuInteraction]):
        class SlashCustomContext(base):
            def __init__(self, *args, **kwargs):
                self.deferred = False
                super().__init__(*args, **kwargs)

            @property
            def created_at(self):
                return snowflake_time(self.id)

            async def defer(self):
                await self.send(type=5)
                self.deferred = True
            
            async def send(self, *args, **kwargs):
                if self.deferred:
                    kwargs.pop("ephemeral", None)
                    return await super().edit(*args, **kwargs)
                return await super().send(*args, **kwargs)
        
        return SlashCustomContext

    @commands.Cog.listener()
    async def on_slash_command(self, ctx: SlashInteraction):
        if ctx.slash_command:
            self.bot.log.info(f"Handling slash command {ctx.slash_command.name} for {ctx.author} in {ctx.guild.name}")
        else:
            self.bot.log.info(f"Attemped to run invalid slash command!")

    @application_commands.slash_command(description="Responds with the bots latency to discords servers")
    async def ping(self, ctx: SlashInteraction):
        gateway = int(self.bot.latency*1000)
        await ctx.send(f"Pong! `{gateway}ms` Gateway") #Message cannot be ephemeral for ping updates to show

    @application_commands.slash_command(description="Owner Only: Reload the bot cogs and listeners")
    @application_commands.is_owner()
    async def reload(self, ctx: SlashInteraction):
        cog_count = 0
        for ext_name in dict(self.bot.extensions).keys():
            cog_count += 1
            self.bot.reload_extension(ext_name)
        await ctx.send(f"<:green_tick:809191812434231316> Succesfully reloaded! Reloaded {cog_count} cogs!", ephemeral=True)
    
    @application_commands.slash_command(description="Owner Only: Run streamer catchup manually")
    @application_commands.is_owner()
    async def catchup(self, ctx: SlashInteraction):
        await ctx.defer()
        self.bot.log.info("Manually Running streamer catchup...")
        await self.bot.catchup_streamers()
        self.bot.log.info("Finished streamer catchup")
        await ctx.send("Finished catchup!", ephemeral=True)

    @application_commands.slash_command(description="Get various bot information such as memory usage and version")
    async def botstatus(self, ctx: SlashInteraction):
        p = pretty_time(self.bot._uptime)
        embed = discord.Embed(title=f"{self.bot.user.name} Status", colour=self.bot.colour, timestamp=utcnow())
        if self.bot.owner_id is None:
            owner_objs = [str(self.bot.get_user(user)) for user in self.bot.owner_ids]
            owners = ', '.join(owner_objs).rstrip(", ")
            is_plural = False
            if len(owner_objs) > 1:
                is_plural = True
        else:
            owners = await self.bot.fetch_user(self.bot.owner_id)
            is_plural = False
        if not getattr(self.bot, "callbacks", None):
            self.bot.callbacks = self.get_callbacks()
        alert_count = 0
        for data in self.bot.callbacks.values():
            alert_count += len(data["alert_roles"].values())
        botinfo = f"**🏠 Servers:** {len(self.bot.guilds)}\n**🤖 Bot Creation Date:** {DiscordTimezone(int(self.bot.user.created_at.timestamp()), TimezoneOptions.month_day_year_time)}\n**🕑 Uptime:** {p.prettify}\n**⚙️ Cogs:** {len(self.bot.cogs)}\n**📈 Commands:** {len([c for c in self.bot.walk_commands()])}\n**🏓 Latency:**  {int(self.bot.latency*1000)}ms\n**🕵️‍♀️ Owner{'s' if is_plural else ''}:** {owners}\n**<:Twitch:891703045908467763> Subscribed Streamers:** {len(self.bot.callbacks.keys())}\n**<:notaggy:891702828756766730> Notification Count:** {alert_count}"
        embed.add_field(name="__Bot__", value=botinfo, inline=False)
        memory = psutil.virtual_memory()
        cpu_freq = psutil.cpu_freq()
        systeminfo = f"**<:python:879586023116529715> Python Version:** {sys.version.split()[0]}\n**<:discordpy:879586265014607893> Discord.py Version:** {discord.__version__}\n**🖥️ CPU:** {psutil.cpu_count()}x @{round((cpu_freq.max if cpu_freq.max != 0 else cpu_freq.current)/1000, 2)}GHz\n**<:microprocessor:879591544070488074> Process Memory Usage:** {psutil.Process(getpid()).memory_info().rss/1048576:.2f}MB\n**<:microprocessor:879591544070488074> System Memory Usage:** {memory.used/1048576:.2f}MB ({memory.percent}%) of {memory.total/1048576:.2f}MB"
        embed.add_field(name="__System__", value=systeminfo, inline=False)
        embed.set_author(name=self.bot.user.name, icon_url=self.bot.user.display_avatar.with_size(128))
        embed.set_footer(text=f"Client ID: {self.bot.user.id}")
        await ctx.send(embed=embed)

    @application_commands.slash_command(description="Get how long the bot has been running")
    async def uptime(self, ctx: SlashInteraction):
        epoch = time() - self.bot._uptime
        conv = {
            "days": str(epoch // 86400).split('.')[0],
            "hours": str(epoch // 3600 % 24).split('.')[0],
            "minutes": str(epoch // 60 % 60).split('.')[0],
            "seconds": str(epoch % 60).split('.')[0],
            "full": strftime('%Y-%m-%d %I:%M:%S %p %Z', localtime(self.bot._uptime))
        }
        description = f"{conv['days']} {'day' if conv['days'] == '1' else 'days'}, {conv['hours']} {'hour' if conv['hours'] == '1' else 'hours'}, {conv['minutes']} {'minute' if conv['minutes'] == '1' else 'minutes'} and {conv['seconds']} {'second' if conv['seconds'] == '1' else 'seconds'}"
        embed = discord.Embed(title="Uptime", description=description,
                            color=self.bot.colour, timestamp=datetime.utcnow())
        embed.set_footer(
            text=f"ID: {ctx.guild.id} | Bot started at {conv['full']}")
        await ctx.send(embed=embed)

    async def aeval(self, ctx: SlashInteraction, code):
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

    @application_commands.slash_command(description="Evalute a string as a command", options=[Option("command", "The string to be evaled", type=OptionType.STRING, required=True), Option("respond", "Should the bot respond with the return values attributes and functions", type=OptionType.BOOLEAN, required=False)])
    @application_commands.is_owner()
    async def eval(self, ctx: SlashInteraction, command, respond=True):
        code_string = "```nim\n{}```"
        if command.startswith("`") and command.endswith("`"):
            command = command[1:][:-1]
        start = time()
        try:
            resp = await self.aeval(ctx, command)
        except Exception as ex:
            await ctx.send(content=f"Exception Occurred: `{type(ex).__name__}: {ex}`")
        else:
            finish = time()
            if not ctx.invoked_with == "evalr":
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
                    if not ctx.invoked_with == "evala":
                        if attr_name.startswith("_"):
                            continue #Most methods/attributes starting with __ or _ are generally unwanted, skip them
                    if type(attr) not in [MethodType, BuiltinFunctionType, FunctionType]:
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
                return_string += [f"Type: {type(resp).__name__}", f"String: {shorten(stred, width=1000)}"] #List return type, it's str value
                if attributes != {}:
                    return_string += ["", "Attributes: "]
                    return_string += [f"{x}:    {shorten(y, width=(106-len(x)))}" for x, y in attributes.items()]

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
                    except discord.errors.NotFound:
                        pass

    async def check_streamer(self, username):
        user = await self.bot.api.get_user(user_login=username)
        if user is None:
            return False
        return user

    async def check_channel_permissions(self, ctx: SlashInteraction, channel):
        if isinstance(channel, int): channel = self.bot.get_channel(channel)
        else: channel = self.bot.get_channel(channel.id)
        if not isinstance(channel, discord.TextChannel):
            raise application_commands.BadArgument(f"Channel {channel.mention} is not a text channel!")

        perms = {"view_channel": True, "read_message_history": True, "send_messages": True}
        permissions = channel.permissions_for(ctx.guild.me)

        missing = [perm for perm, value in perms.items() if getattr(permissions, perm) != value]
        if not missing:
            return True

        raise application_commands.BotMissingPermissions(missing)

    @application_commands.slash_command(name="addstreamer", description="Add alerts for the specific streamer", options=[
        Option("streamer", description="The streamer username you want to add the alert for", type=OptionType.STRING, required=True),
        Option("alert_mode", description="The type of notification setup you want", type=OptionType.INTEGER, required=True, choices=[
            OptionChoice("Mode 0 - Creates a temporary channel when the streamer is live", 0),
            OptionChoice("Mode 2 - Updates a persistent status channel when the streamer goes live and offline.", 2)
        ]),
        Option("notification_channel", description="The channel to send live notifications in", type=OptionType.CHANNEL, required=True),
        Option("role", description="The role you want the bot to mention when the streamer goes live", type=OptionType.ROLE, required=False),
        Option("status_channel", description="The persistent channel to be used. This option is only required if you select mode 2", type=OptionType.CHANNEL, required=False)
    ])
    @application_commands.has_guild_permissions(administrator=True)
    async def addstreamer(self, ctx: SlashInteraction, streamer, alert_mode, notification_channel, role = None, status_channel=None):
        # Run checks on all the supplied arguments
        streamer_search = streamer
        streamer = await self.check_streamer(username=streamer)
        if not streamer:
            raise application_commands.BadArgument(f"Could not find twitch user {streamer_search}!")
        await self.check_channel_permissions(ctx, channel=notification_channel)
        if status_channel is not None:
            await self.check_channel_permissions(ctx, channel=status_channel)

        if isinstance(notification_channel, int): notification_channel = self.bot.get_channel(notification_channel)
        if isinstance(status_channel, int): status_channel = self.bot.get_channel(status_channel)
        
        if alert_mode == 2 and status_channel is None:
            raise application_commands.BadArgument(f"Alert Mode 2 requires a status channel!")

        #Checks done

        #Create file structure and subscriptions if necessary
        if not getattr(self.bot, "callbacks", None):
            self.bot.callbacks = await self.get_callbacks()
        
        
        make_subscriptions = False
        if streamer.username not in self.bot.callbacks.keys():
            make_subscriptions = True
            self.bot.callbacks[streamer.username] = {"channel_id": streamer.id, "secret": await random_string_generator(21), "alert_roles": {}}

        self.bot.callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)] = {"mode": alert_mode, "notif_channel_id": notification_channel.id}
        if role == None:
            self.bot.callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["role_id"] = None
        elif role == ctx.guild.default_role:
            self.bot.callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["role_id"] = "everyone"
        else:
            self.bot.callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["role_id"] = role.id
        if alert_mode == 2:
            self.bot.callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["channel_id"] = status_channel.id

        await self.write_callbacks(self.bot.callbacks)

        if make_subscriptions:
            await ctx.defer()
            try:
                sub1 = await self.bot.api.create_subscription(SubscriptionType.STREAM_ONLINE, streamer=streamer, secret=self.bot.callbacks[streamer.username]["secret"])
                self.bot.callbacks[streamer.username]["online_id"] = sub1.id
                sub2 = await self.bot.api.create_subscription(SubscriptionType.STREAM_OFFLINE, streamer=streamer, secret=self.bot.callbacks[streamer.username]["secret"])
                self.bot.callbacks[streamer.username]["offline_id"] = sub2.id
            except SubscriptionError as e:
                await self.callback_deletion(ctx, streamer.username, config_file="title_callbacks.json", _type="title")
                raise SubscriptionError(str(e))

        await self.write_callbacks(self.bot.callbacks)

        #Run catchup on streamer immediately
        stream_status = await self.bot.api.get_stream(streamer.username)
        if stream_status is None:
            if status_channel is not None:
                await status_channel.edit(name="stream-offline")
            self.bot.dispatch("streamer_offline", streamer)
        else:
            self.bot.dispatch("streamer_online", stream_status)

        embed = discord.Embed(title="Successfully added new streamer", color=self.bot.colour)
        embed.add_field(name="Streamer", value=streamer.username, inline=True)
        embed.add_field(name="Notification Channel", value=notification_channel, inline=True)
        embed.add_field(name="Alert Role", value=role, inline=True)
        embed.add_field(name="Alert Mode", value=alert_mode, inline=True)
        if alert_mode == 2:
            embed.add_field(name="Status Channel", value=status_channel.mention, inline=True)
        await ctx.send(embed=embed)

    @application_commands.slash_command(description="List all the active streamer alerts setup in this server")
    @application_commands.has_guild_permissions(administrator=True)
    async def liststreamers(self, ctx: SlashInteraction):
        if not getattr(self.bot, "callbacks", None):
            self.bot.callbacks = await self.get_callbacks()

        uwu = f"```nim\n{'Channel':15s} {'Alert Role':25s} {'Alert Channel':18s} Alert Mode \n"
        for x, y in self.bot.callbacks.items():
            if str(ctx.guild.id) in y["alert_roles"].keys():
                info = y["alert_roles"][str(ctx.guild.id)]
                alert_role = info.get("role_id", None)
                if alert_role is None:
                    alert_role = "<No Alert Role>"
                elif alert_role == "everyone":
                    alert_role == "@everyone"
                else:
                    try:
                        alert_role: Union[discord.Role, None] = ctx.guild.get_role(int(alert_role))
                    except ValueError:
                        alert_role = ""
                    else:
                        if alert_role is not None:
                            alert_role = alert_role.name
                        else:
                            alert_role = "@deleted-role"

                channel_override = info.get("notif_channel_id", None)
                channel_override: Union[discord.TextChannel, None] = ctx.guild.get_channel(channel_override)
                if channel_override is not None:
                    channel_override = "#" + channel_override.name
                else:
                    channel_override = ""

                if len(uwu + f"{x:15s} {alert_role:25s} {channel_override:18s} {info.get('mode', 2)}\n") > 1800:
                    uwu += "```"
                    await ctx.send(uwu)
                    uwu = "```nim\n"
                uwu += f"{x:15s} {alert_role:25s} {channel_override:18s} {info.get('mode', 2)}\n"
        uwu += "```"
        await ctx.send(uwu)

    @application_commands.slash_command(description="List all the active title change alerts setup in this server")
    @application_commands.has_guild_permissions(administrator=True)
    async def listtitlechanges(self, ctx: SlashInteraction):
        if not getattr(self.bot, "title_callbacks", None):
            self.bot.title_callbacks = await self.get_title_callbacks()
        uwu = f"```nim\n{'Channel':15s} {'Alert Role':35s} {'Alert Channel':18s}\n"
        for x, y in self.bot.title_callbacks.items():
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
                        alert_role: Union[discord.Role, None] = ctx.guild.get_role(alert_role)
                        if alert_role is not None:
                            alert_role = alert_role.name
                        else:
                            alert_role = ""

                alert_channel = info.get("notif_channel_id", None)
                alert_channel: Union[discord.TextChannel, None] = ctx.guild.get_channel(alert_channel)
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

    @application_commands.slash_command(description="Add alerts for the specific streamer", options=[
        Option("streamer", description="The streamer username you want to add the alert for", type=OptionType.STRING, required=True),
        Option("notification_channel", description="The channel to send live notifications in", type=OptionType.CHANNEL, required=True),
        Option("role", description="The role you want the bot to mention when the streamer goes live", type=OptionType.ROLE, required=False)
    ])
    @application_commands.has_guild_permissions(administrator=True)
    async def addtitlechange(self, ctx: SlashInteraction, streamer, notification_channel, role = None):
        # Run checks on all the supplied arguments
        streamer_search = streamer
        streamer = await self.check_streamer(username=streamer)
        if not streamer:
            raise application_commands.BadArgument(f"Could not find twitch user {streamer_search}!")
        await self.check_channel_permissions(ctx, channel=notification_channel)

        #Checks done
        if isinstance(notification_channel, int): notification_channel = self.bot.get_channel(notification_channel)

        #Create file structure and subscriptions if necessary
        if not getattr(self.bot, "title_callbacks", None):
            self.bot.title_callbacks = await self.get_title_callbacks()
        
        make_subscriptions = False
        if streamer.username not in self.bot.title_callbacks.keys():
            make_subscriptions = True
            self.bot.title_callbacks[streamer.username] = {"channel_id": streamer.id, "secret": await random_string_generator(21), "alert_roles": {}}
            
        self.bot.title_callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)] = {"notif_channel_id": notification_channel.id}
        if role == None:
            self.bot.title_callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["role_id"] = None
        elif role == ctx.guild.default_role:
            self.bot.title_callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["role_id"] = "everyone"
        else:
            self.bot.title_callbacks[streamer.username]["alert_roles"][str(ctx.guild.id)]["role_id"] = role.id

        await self.write_title_callbacks(self.bot.title_callbacks)

        if make_subscriptions:
            await ctx.defer()
            try:
                sub = await self.bot.api.create_subscription(SubscriptionType.CHANNEL_UPDATE, streamer=streamer, _type="titlecallback", secret=self.bot.title_callbacks[streamer.username]["secret"])
            except SubscriptionError as e:
                await self.callback_deletion(ctx, streamer.username, config_file="title_callbacks.json", _type="title")
                raise SubscriptionError(str(e))
            self.bot.title_callbacks[streamer.username]["subscription_id"] = sub.id

        await self.write_title_callbacks(self.bot.title_callbacks)

        embed = discord.Embed(title="Successfully added new title change alert", color=self.bot.colour)
        embed.add_field(name="Streamer", value=streamer.username, inline=True)
        embed.add_field(name="Notification Channel", value=notification_channel, inline=True)
        embed.add_field(name="Alert Role", value=role, inline=True)
        await ctx.send(embed=embed)

    @application_commands.slash_command(description="Remove a live notification alert", options=[Option("streamer", "The name of the streamer to be removed", type=OptionType.STRING, required=True)])
    @application_commands.has_guild_permissions(administrator=True)
    async def delstreamer(self, ctx: SlashInteraction, streamer: str):
        await self.callback_deletion(ctx, streamer, config_file="callbacks.json", _type="status")
        embed = discord.Embed(title="Streamer Removed", description=f"Deleted alert for {streamer}", colour=self.bot.colour)
        await ctx.send(embed=embed)

    @application_commands.slash_command(description="Remove a title change alert", options=[Option("streamer", "The name of the streamer to be removed", type=OptionType.STRING, required=True)])
    @application_commands.has_guild_permissions(administrator=True)
    async def deltitlechange(self, ctx: SlashInteraction, streamer: str):
        await self.callback_deletion(ctx, streamer, config_file="title_callbacks.json", _type="title")
        embed = discord.Embed(title="Streamer Removed", description=f"Deleted title change alert for {streamer}", colour=self.bot.colour)
        await ctx.send(embed=embed)

    async def callback_deletion(self, ctx: SlashInteraction, streamer, config_file, _type="status"):
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
            embed = discord.Embed(title="Error", description="<:red_tick:809191812337369118> Streamer not found for server", colour=self.bot.colour)
            await ctx.send(embed=embed)
            return
        if callbacks[streamer]["alert_roles"] == {}:
            self.bot.log.info(f"Streamer {streamer} has no more alerts, purging")
            try:
                if _type == "title":
                    await self.bot.api.delete_subscription(callbacks[streamer]['subscription_id'])
                elif _type == "status":
                    await self.bot.api.delete_subscription(callbacks[streamer]['offline_id'])
                    await self.bot.api.delete_subscription(callbacks[streamer]['online_id'])
            except KeyError:
                pass
            del callbacks[streamer]
        async with aiofiles.open(f"config/{config_file}", "w") as f:
            await f.write(json.dumps(callbacks, indent=4))

    @application_commands.slash_command(description="Owner Only: Test if callback is functioning correctly")
    @application_commands.is_owner()
    async def testcallback(self, ctx: SlashInteraction):
        await ctx.defer()
        #This is just a shitty quick implementation. The web server should always return a status code 400 since no streamer should ever be named _callbacktest
        try:
            r = await self.bot.api._request(f"{self.bot.api.callback_url}/callback/_callbacktest", method="POST")
        except asyncio.TimeoutError:
            return await ctx.send(f"Callback test failed. Server timed out")
        if r.status == 204:
            await ctx.send("Callback Test Successful. Returned expected HTTP status code 204")
        else:
            await ctx.send(f"Callback test failed. Expected HTTP status code 204 but got {r.status}")


    @application_commands.slash_command(description="Owner Only: Resubscribe every setup callback. Useful for domain changes")
    @application_commands.is_owner()
    async def resubscribe(self, ctx: SlashInteraction):
        self.bot.log.info("Running live alert resubscribe")
        await ctx.defer()
        if not getattr(self.bot, "callbacks", None):
            self.bot.callbacks = await self.get_callbacks()
        for streamer, data in self.bot.callbacks.items():
            await asyncio.sleep(0.2)
            if data.get("online_id", None) is not None:
                await self.bot.api.delete_subscription(data["online_id"])
            rj1 = await self.bot.api.create_subscription(SubscriptionType.STREAM_ONLINE, streamer=PartialUser(data["channel_id"], streamer, streamer), secret=data["secret"])
            await asyncio.sleep(0.2)
            self.bot.callbacks[streamer]["online_id"] = rj1.id
            if data.get("offline_id", None) is not None:
                await self.bot.api.delete_subscription(data["offline_id"])
            rj2 = await self.bot.api.create_subscription(SubscriptionType.STREAM_OFFLINE, streamer=PartialUser(data["channel_id"], streamer, streamer), secret=data["secret"])
            self.bot.callbacks[streamer]["offline_id"] = rj2.id
        await self.write_callbacks(self.bot.callbacks)

        self.bot.log.info("Running title resubscribe")
        if not getattr(self.bot, "title_callbacks", None):
            await self.get_title_callbacks()
        for streamer, data in self.bot.title_callbacks.items():
            await asyncio.sleep(0.2)
            if data.get("subscription_id", None) is not None:
                await self.bot.api.delete_subscription(data["subscription_id"])
            sub = await self.bot.api.create_subscription(SubscriptionType.CHANNEL_UPDATE, streamer=PartialUser(data["channel_id"], streamer, streamer), secret=data["secret"])
            await asyncio.sleep(0.2)
            self.bot.title_callbacks[streamer]["subscription_id"] = sub.id
        self.write_title_callbacks(self.bot.title_callbacks)
        await ctx.send("Done")
                


            
async def random_string_generator(str_size):
    return "".join(choice(ascii_letters) for _ in range(str_size))


def setup(bot):
    bot.add_cog(RecieverCommands(bot))