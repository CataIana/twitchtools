from discord import ChannelType, Embed, TextChannel, AllowedMentions, NotFound, HTTPException
from discord.ext import commands, tasks
from discord.utils import utcnow
from dislash import slash_command, Option, OptionType, OptionChoice, is_owner, SlashInteraction, BadArgument, BotMissingPermissions, ApplicationCommandError
from dislash import has_guild_permissions
import discord
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
from enum import Enum


class SubscriptionError(ApplicationCommandError):
    def __init__(self, message = None):
        super().__init__(message or "There was an error handling the eventsub subscription")

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
    def __init__(self, bot):
        self.bot = bot
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
    async def on_slash_command(self, ctx):
        self.bot.log.info(f"Handling slash command {ctx.slash_command.name} for {ctx.author} in {ctx.guild.name}")

    class CustomContext(commands.Context):
        async def send(self, content=None, **kwargs):
            allowed_mentions = kwargs.pop("allowed_mentions", AllowedMentions(everyone=False, roles=False, replied_user=(True if self.author in self.message.mentions else False)))
            kwargs.pop("ephemeral", None) #Remove possible slash command attributes
            try:
                return await self.reply(content, **kwargs, allowed_mentions=allowed_mentions)
            except HTTPException:
                return await super().send(content, **kwargs, allowed_mentions=allowed_mentions)

        async def send_noreply(self, content=None, **kwargs):
            allowed_mentions = kwargs.pop("allowed_mentions", AllowedMentions(everyone=False, roles=False, replied_user=(True if self.author in self.message.mentions else False)))
            return await super().send(content, **kwargs, allowed_mentions=allowed_mentions)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.content == "Pong!" and message.author == self.bot.user:
            rest = int(((utcnow() - message.created_at).microseconds)/1000)
            gateway = int(self.bot.latency*1000)
            await message.edit(content=f"Pong! `{rest}ms` Rest | `{gateway}ms` Gateway")

        if message.channel.type == ChannelType.private:
            return

        p = message.channel.permissions_for(message.guild.me)
        if not p.send_messages and not p.embed_links:
            return

        if message.author.bot or message.author == self.bot.user:
            return

        ctx = await self.bot.get_context(message, cls=self.CustomContext)
        await self.bot.invoke(ctx)

    @slash_command(description="Responds with the bots latency to discords servers")
    async def ping(self, ctx):
        await ctx.send(content="Pong!") #Message cannot be ephemeral for ping updates to show

    @slash_command(description="Owner Only: Reload the bot cogs and listeners")
    @is_owner()
    async def reload(self, ctx):
        await ctx.channel.trigger_typing()
        cog_count = 0
        for ext_name in dict(self.bot.extensions).keys():
            cog_count += 1
            self.bot.reload_extension(ext_name)
        await ctx.send(content=f"<:green_tick:809191812434231316> Succesfully reloaded! Reloaded {cog_count} cogs!", ephemeral=True)
    
    @slash_command(description="Owner Only: Run streamer catchup manually")
    @is_owner()
    async def catchup(self, ctx):
        self.bot.log.info("Manually Running streamer catchup...")
        await self.bot.catchup_streamers()
        self.bot.log.info("Finished streamer catchup")
        await ctx.send("Finished catchup!", ephemeral=True)

    @slash_command(description="Get various bot information such as memory usage and version")
    async def botstatus(self, ctx):
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
        async with aiofiles.open("config/callbacks.json") as f:
            callbacks = json.loads(await f.read())
        alert_count = 0
        for data in callbacks.values():
            alert_count += len(data["alert_roles"].values())
        botinfo = f"**🏠 Servers:** {len(self.bot.guilds)}\n**🤖 Bot Creation Date:** {DiscordTimezone(int(self.bot.user.created_at.timestamp()), TimezoneOptions.month_day_year_time)}\n**🕑 Uptime:** {p.prettify}\n**⚙️ Cogs:** {len(self.bot.cogs)}\n**📈 Commands:** {len([c for c in self.bot.walk_commands()])}\n**🏓 Latency:**  {int(self.bot.latency*1000)}ms\n**🕵️‍♀️ Owner{'s' if is_plural else ''}:** {owners}\n**<:Twitch:891703045908467763> Subscribed Streamers:** {len(callbacks.keys())}\n**<:notaggy:891702828756766730> Notification Count:** {alert_count}"
        embed.add_field(name="__Bot__", value=botinfo, inline=False)
        memory = psutil.virtual_memory()
        cpu_freq = psutil.cpu_freq()
        systeminfo = f"**<:python:879586023116529715> Python Version:** {sys.version.split()[0]}\n**<:discordpy:879586265014607893> Discord.py Version:** {discord.__version__}\n**🖥️ CPU:** {psutil.cpu_count()}x @{round((cpu_freq.max if cpu_freq.max != 0 else cpu_freq.current)/1000, 2)}GHz\n**<:microprocessor:879591544070488074> Process Memory Usage:** {psutil.Process(getpid()).memory_info().rss/1048576:.2f}MB\n**<:microprocessor:879591544070488074> System Memory Usage:** {memory.used/1048576:.2f}MB ({memory.percent}%) of {memory.total/1048576:.2f}MB"
        embed.add_field(name="__System__", value=systeminfo, inline=False)
        embed.set_author(name=self.bot.user.name, icon_url=self.bot.user.display_avatar.with_size(128))
        embed.set_footer(text=f"Client ID: {self.bot.user.id}")
        await ctx.send(embed=embed, ephemeral=True)

    @slash_command(description="Get how long the bot has been running")
    async def uptime(self, ctx):
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

    async def aeval(self, ctx, code):
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

    # @slash_command(description="Evalute a string as a command")
    # async def eval(self, ctx: SlashInteraction,
    #     command: str = OptionParam(description="The string to be evaluated"),
    #     respond: bool = OptionParam(True, description="Respond with attributes and functions?"),
    # ):
    @slash_command(description="Evalute a string as a command", options=[Option("command", "The string to be evaled", type=OptionType.STRING, required=True), Option("respond", "Should the bot respond with the return values attributes and functions", type=OptionType.BOOLEAN, required=False)])
    @is_owner()
    async def eval(self, ctx: SlashInteraction, command, respond=True):
        code_string = "```nim\n{}```"
        if command.startswith("`") and command.endswith("`"):
            command = command[1:][:-1]
        try:
            resp = await self.aeval(ctx, command)
        except Exception as ex:
            await ctx.send(content=f"Exception Occurred: `{ex}`")
        else:
            if not ctx.invoked_with == "evalr" and respond:
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
                    if attr_name.startswith("_"):
                        continue #Most methods/attributes starting with __ or _ are generally unwanted, skip them
                    if type(attr) not in [MethodType, BuiltinFunctionType, FunctionType]:
                        attributes[str(attr_name)] = f"{attr} [{type(attr).__name__}]"
                    else:
                        if asyncio.iscoroutinefunction(attr):
                            amethods.append(attr_name)
                        else:
                            methods.append(attr_name)
                if attributes == {}:
                    attributes["str"] = str(resp)

                #Form the long ass string of everything
                return_string = []
                if type(resp) != list:
                    stred = str(resp)
                else:
                    stred = '\n'.join([str(r) for r in resp])
                return_string += [f"Type: {type(resp).__name__}", f"Str: {stred}", '', "Attributes:"] #List return type, it's str value
                return_string += [f"{x}:    {y}" for x, y in attributes.items()]

                if methods != []:
                    return_string.append("\nMethods:")
                    return_string.append(', '.join([method for method in methods]).rstrip(", "))

                if amethods != []:
                    return_string.append("\n\nAsync/Awaitable Methods:")
                    return_string.append(', '.join([method for method in amethods]).rstrip(", "))

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
                    except NotFound:
                        pass

    async def check_streamer(self, username):
        response = await self.bot.api_request(f"https://api.twitch.tv/helix/users?login={username}")
        r_json = await response.json()
        if r_json["data"] != []:
            return r_json["data"][0]
        else:
            return False

    async def check_channel_permissions(self, ctx, channel):
        if isinstance(channel, int): channel = self.bot.get_channel(channel)
        else: channel = self.bot.get_channel(channel.id)
        if not isinstance(channel, TextChannel):
            raise BadArgument(f"Channel {channel.mention} is not a text channel!")

        perms = {"view_channel": True, "read_message_history": True, "send_messages": True}
        permissions = channel.permissions_for(ctx.guild.me)

        missing = [perm for perm, value in perms.items() if getattr(permissions, perm) != value]
        if not missing:
            return True

        raise BotMissingPermissions(missing)

    @slash_command(name="addstreamer", description="Add alerts for the specific streamer", options=[
        Option("streamer", description="The streamer username you want to add the alert for", type=OptionType.STRING, required=True),
        Option("alert_mode", description="The type of notification setup you want", type=OptionType.INTEGER, required=True, choices=[
            OptionChoice("Mode 0 - Creates a temporary channel when the streamer is live", 0),
            OptionChoice("Mode 2 - Updates a persistent status channel when the streamer goes live and offline.", 2)
        ]),
        Option("notification_channel", description="The channel to send live notifications in", type=OptionType.CHANNEL, required=True),
        Option("role", description="The role you want the bot to mention when the streamer goes live", type=OptionType.ROLE, required=False),
        Option("status_channel", description="The persistent channel to be used. This option is only required if you select mode 2", type=OptionType.CHANNEL, required=False)
    ])
    @has_guild_permissions(administrator=True)
    async def addstreamer(self, ctx: SlashInteraction, streamer, alert_mode, notification_channel, role = None, status_channel=None):
        # Run checks on all the supplied arguments
        streamer_info = await self.check_streamer(username=streamer)
        if not streamer_info:
            raise BadArgument(f"Could not find twitch user {streamer}!")
        await self.check_channel_permissions(ctx, channel=notification_channel)
        if status_channel is not None:
            await self.check_channel_permissions(ctx, channel=status_channel)

        if isinstance(notification_channel, int): notification_channel = self.bot.get_channel(notification_channel)
        if isinstance(status_channel, int): status_channel = self.bot.get_channel(status_channel)
        
        if alert_mode == 2 and status_channel is None:
            raise BadArgument(f"Alert Mode 2 requires a status channel!")

        #Checks done

        #Create file structure and subscriptions if necessary
        try:
            async with aiofiles.open("config/callbacks.json") as f:
                callbacks = json.loads(await f.read())
        except FileNotFoundError:
            callbacks = {}
        except JSONDecodeError:
            callbacks = {}
        
        if streamer not in callbacks.keys():
            callbacks[streamer] = {"channel_id": streamer_info["id"], "secret": await random_string_generator(21), "alert_roles": {}}
            response = await self.bot.api_request("https://api.twitch.tv/helix/eventsub/subscriptions",
                json={
                    "type": "stream.online",
                    "version": "1",
                    "condition": {
                        "broadcaster_user_id": streamer_info["id"]
                    },
                    "transport": {
                        "method": "webhook",
                        "callback": f"{self.bot.auth['callback_url']}/callback/{streamer}",
                        "secret": callbacks[streamer]["secret"]
                    }
                }, method="post")
            response2 = await self.bot.api_request("https://api.twitch.tv/helix/eventsub/subscriptions",
                json={
                    "type": "stream.offline",
                    "version": "1",
                    "condition": {
                        "broadcaster_user_id": streamer_info["id"]
                    },
                    "transport": {
                        "method": "webhook",
                        "callback": f"{self.bot.auth['callback_url']}/callback/{streamer}",
                        "secret": callbacks[streamer]["secret"]
                    }
                }, method="post")
            if response.status not in [202, 409]:
                raise SubscriptionError(f"There was an error subscribing to the stream online eventsub. Please try again later. Error code: {response.status_code}")
            if response2.status not in [202, 409]:
                raise SubscriptionError(f"There was an error subscribing to the stream online eventsub. Please try again later. Error code: {response.status_code}")
            json1 = await response.json()
            json2 = await response2.json()
            callbacks[streamer]["online_id"] = json1["data"][0]["id"]
            callbacks[streamer]["offline_id"] = json2["data"][0]["id"]
        callbacks[streamer]["alert_roles"][str(ctx.guild.id)] = {"mode": alert_mode, "notif_channel_id": notification_channel.id}
        if role == None:
            callbacks[streamer]["alert_roles"][str(ctx.guild.id)]["role_id"] = None
        elif role == ctx.guild.default_role:
            callbacks[streamer]["alert_roles"][str(ctx.guild.id)]["role_id"] = "everyone"
        else:
            callbacks[streamer]["alert_roles"][str(ctx.guild.id)]["role_id"] = role.id
        if alert_mode == 2:
            callbacks[streamer]["alert_roles"][str(ctx.guild.id)]["channel_id"] = status_channel.id

        async with aiofiles.open("config/callbacks.json", "w") as f:
            await f.write(json.dumps(callbacks, indent=4))

        #Run catchup on streamer immediately
        response = await self.bot.api_request(f"https://api.twitch.tv/helix/streams?user_login={streamer}")
        response = await response.json()
        if response["data"] == []:
            if status_channel is not None:
                await status_channel.edit(name="stream-offline")
            await self.bot.streamer_offline(streamer)
        else:
            await self.bot.streamer_online(streamer, response["data"][0])

        embed = Embed(title="Successfully added new streamer", color=self.bot.colour)
        embed.add_field(name="Streamer", value=streamer, inline=True)
        embed.add_field(name="Notification Channel", value=notification_channel, inline=True)
        embed.add_field(name="Alert Role", value=role, inline=True)
        embed.add_field(name="Alert Mode", value=alert_mode, inline=True)
        if alert_mode == 2:
            embed.add_field(name="Status Channel", value=status_channel.mention, inline=True)
        await ctx.send(embed=embed, ephemeral=True)

    @slash_command(description="List all the active streamer alerts setup in this server")
    @has_guild_permissions(administrator=True)
    async def liststreamers(self, ctx):
        try:
            async with aiofiles.open("config/callbacks.json") as f:
                callback_info = json.loads(await f.read())
        except FileNotFoundError:
            await ctx.send("Error reading config files. Please try again later", ephemeral=True)
            return
        except JSONDecodeError:
            await ctx.send("Error reading config files. Please try again later", ephemeral=True)
            return            

        uwu = f"```nim\n{'Channel':15s} {'Alert Role':25s} {'Alert Channel':18s} Alert Mode \n"
        ephemeral = True
        for x, y in callback_info.items():
            if str(ctx.guild.id) in y["alert_roles"].keys():
                info = y["alert_roles"][str(ctx.guild.id)]
                alert_role = info.get("role_id", None)
                if alert_role is None:
                    alert_role = "<No Alert Role>"
                elif alert_role == "everyone":
                    alert_role == "@everyone"
                else:
                    try:
                        alert_role = ctx.guild.get_role(int(alert_role))
                    except ValueError:
                        alert_role = ""
                    else:
                        if alert_role is not None:
                            alert_role = alert_role.name
                        else:
                            alert_role = "@deleted-role"

                channel_override = info.get("notif_channel_id", None)
                channel_override = ctx.guild.get_channel(channel_override)
                if channel_override is not None:
                    channel_override = "#" + channel_override.name
                else:
                    channel_override = ""

                if len(uwu + f"{x:15s} {alert_role:25s} {channel_override:18s} {info.get('mode', 2)}\n") > 1800:
                    uwu += "```"
                    ephemeral = False
                    await ctx.send(uwu)
                    uwu = "```nim\n"
                uwu += f"{x:15s} {alert_role:25s} {channel_override:18s} {info.get('mode', 2)}\n"
        uwu += "```"
        await ctx.send(uwu, ephemeral=ephemeral)

    @slash_command(description="List all the active title change alerts setup in this server")
    @has_guild_permissions(administrator=True)
    async def listtitlechanges(self, ctx):
        async with aiofiles.open("config/title_callbacks.json") as f:
            callback_info = json.loads(await f.read())
        ephemeral = True
        uwu = f"```nim\n{'Channel':15s} {'Alert Role':35s} {'Alert Channel':18s}\n"
        for x, y in callback_info.items():
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
                        alert_role = ctx.guild.get_role(alert_role)
                        if alert_role is not None:
                            alert_role = alert_role.name
                        else:
                            alert_role = ""

                alert_channel = info.get("notif_channel_id", None)
                alert_channel = ctx.guild.get_channel(alert_channel)
                if alert_channel is not None:
                    alert_channel = "#" + alert_channel.name
                else:
                    alert_channel = ""

                if len(uwu + f"{x:15s} {alert_role:35s} {alert_channel:18s}\n") > 1800:
                    uwu += "```"
                    ephemeral = False
                    await ctx.send(uwu)
                    uwu = "```nim\n"
                uwu += f"{x:15s} {alert_role:35s} {alert_channel:18s}\n"
        uwu += "```"
        await ctx.send(uwu, ephemeral=ephemeral)

    @slash_command(description="Add alerts for the specific streamer", options=[
        Option("streamer", description="The streamer username you want to add the alert for", type=OptionType.STRING, required=True),
        Option("notification_channel", description="The channel to send live notifications in", type=OptionType.CHANNEL, required=True),
        Option("role", description="The role you want the bot to mention when the streamer goes live", type=OptionType.ROLE, required=False)
    ], test_guilds=[749646865531928628])
    @has_guild_permissions(administrator=True)
    async def addtitlechange(self, ctx: SlashInteraction, streamer, notification_channel, role = None):
        # Run checks on all the supplied arguments
        streamer_info = await self.check_streamer(username=streamer)
        if not streamer_info:
            raise BadArgument(f"Could not find twitch user {streamer}!")
        await self.check_channel_permissions(ctx, channel=notification_channel)

        #Checks done
        self.bot.log.info(role)
        if isinstance(notification_channel, int): notification_channel = self.bot.get_channel(notification_channel)

        #Create file structure and subscriptions if necessary
        try:
            async with aiofiles.open("config/title_callbacks.json") as f:
                callbacks = json.loads(await f.read())
        except FileNotFoundError:
            callbacks = {}
        except JSONDecodeError:
            callbacks = {}
        
        if streamer not in callbacks.keys():
            callbacks[streamer] = {"channel_id": streamer_info["id"], "secret": await random_string_generator(21), "alert_roles": {}}
            response = await self.bot.api_request("https://api.twitch.tv/helix/eventsub/subscriptions",
                json={
                    "type": "channel.update",
                    "version": "1",
                    "condition": {
                        "broadcaster_user_id": streamer_info["id"]
                    },
                    "transport": {
                        "method": "webhook",
                        "callback": f"{self.bot.auth['callback_url']}/titlecallback/{streamer}",
                        "secret": callbacks[streamer]["secret"]
                    }
                }, method="post")
            if response.status not in [202, 409]:
                raise SubscriptionError(f"There was an error subscribing to the stream online eventsub. Please try again later. Error code: {response.status_code}")
            json1 = await response.json()
            callbacks[streamer]["subscription_id"] = json1["data"][0]["id"]
        callbacks[streamer]["alert_roles"][str(ctx.guild.id)] = {"notif_channel_id": notification_channel.id}
        if role == None:
            callbacks[streamer]["alert_roles"][str(ctx.guild.id)]["role_id"] = None
        elif role == ctx.guild.default_role:
            callbacks[streamer]["alert_roles"][str(ctx.guild.id)]["role_id"] = "everyone"
        else:
            callbacks[streamer]["alert_roles"][str(ctx.guild.id)]["role_id"] = role.id

        async with aiofiles.open("config/title_callbacks.json", "w") as f:
            await f.write(json.dumps(callbacks, indent=4))

        embed = Embed(title="Successfully added new title change alert", color=self.bot.colour)
        embed.add_field(name="Streamer", value=streamer, inline=True)
        embed.add_field(name="Notification Channel", value=notification_channel, inline=True)
        embed.add_field(name="Alert Role", value=role, inline=True)
        await ctx.send(embed=embed, ephemeral=True)

    @slash_command(description="Remove a live notification alert", options=[Option("streamer", "The name of the streamer to be removed", type=OptionType.STRING, required=True)])
    @has_guild_permissions(administrator=True)
    async def delstreamer(self, ctx, streamer: str):
        await self.callback_deletion(ctx, streamer, config_file="callbacks.json", _type="status")

    @slash_command(description="Remove a title change alert", options=[Option("streamer", "The name of the streamer to be removed", type=OptionType.STRING, required=True)])
    @has_guild_permissions(administrator=True)
    async def deltitlechange(self, ctx, streamer: str):
        await self.callback_deletion(ctx, streamer, config_file="title_callbacks.json", _type="title")

    async def callback_deletion(self, ctx, streamer, config_file, _type="status"):
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
            embed = Embed(title="Error", description="<:red_tick:809191812337369118> Streamer not found for server", colour=self.bot.colour)
            await ctx.send(embed=embed)
            return
        if callbacks[streamer]["alert_roles"] == {}:
            self.bot.log.info(f"Streamer {streamer} has no more alerts, purging")
            try:
                if _type == "title":
                    await self.bot.api_request(f"https://api.twitch.tv/helix/eventsub/subscriptions?id={callbacks[streamer]['subscription_id']}", method="delete")
                elif _type == "status":
                    await self.bot.api_request(f"https://api.twitch.tv/helix/eventsub/subscriptions?id={callbacks[streamer]['offline_id']}", method="delete")
                    await self.bot.api_request(f"https://api.twitch.tv/helix/eventsub/subscriptions?id={callbacks[streamer]['online_id']}", method="delete")
            except KeyError:
                pass
            del callbacks[streamer]
        async with aiofiles.open(f"config/{config_file}", "w") as f:
            await f.write(json.dumps(callbacks, indent=4))
        if _type == "title":
            embed = Embed(title="Streamer Removed", description=f"Deleted title change alert for {streamer}", colour=self.bot.colour)
        elif _type == "status":
            embed = Embed(title="Streamer Removed", description=f"Deleted alert for {streamer}", colour=self.bot.colour)
        else:
            return
        return await ctx.send(embed=embed, ephemeral=True)


            
async def random_string_generator(str_size):
    return "".join(choice(ascii_letters) for _ in range(str_size))


def setup(bot):
    bot.add_cog(RecieverCommands(bot))