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

import disnake
import psutil
from disnake import Embed, Role, TextChannel
from disnake.ext import commands
from disnake.utils import utcnow
from munch import munchify

from main import TwitchCallBackBot
from twitchtools import (AlertOrigin, AlertType, ApplicationCustomContext,
                         Callback, Confirm, PartialUser, PartialYoutubeUser,
                         PlatformChoice, SortableTextPaginator,
                         SubscriptionError, SubscriptionType, TextPaginator,
                         User, UserType, YoutubeCallback, YoutubeSubscription,
                         YoutubeUser, check_channel_permissions,
                         has_guild_permissions, has_manage_permissions,
                         human_timedelta)

LEASE_SECONDS = 828000

READABLE_MODES = {
    0: "Notification + Temp Channel",
    1: "Notification Only",
    2: "Notification + Persistent Channel"
}


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
                f"[Command] Triggered {ctx.application_command.qualified_name} by {ctx.author} in {ctx.guild.name}")
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
            alert_count += len(data.alert_roles.values())
        yt_callbacks = await self.bot.db.get_all_yt_callbacks()
        yt_alert_count = 0
        for data in yt_callbacks.values():
            yt_alert_count += len(data.alert_roles.values())
        botinfo = f"**🏠 Servers:** {len(self.bot.guilds)}\n**🤖 Bot Creation Date:** {DiscordTimezone(int(self.bot.user.created_at.timestamp()), TimestampOptions.long_date_short_time)}\n**🕑 Uptime:** {human_timedelta(datetime.utcfromtimestamp(self.bot._uptime), suffix=False)}\n**🏓 Latency:**  {int(self.bot.latency*1000)}ms\n**🕵️‍♀️ Owner{'s' if is_plural else ''}:** {owners}\n**<:Twitch:891703045908467763> Subscribed Twitch Streamers:** {len(callbacks.keys())}\n**<:Youtube:1034338274220703756> Subscribed YT Channels:** {len(yt_callbacks.keys())}\n**<:notaggy:891702828756766730> Twitch Notification Count:** {alert_count}\n**<:notaggy:891702828756766730> Youtube Notification Count:** {yt_alert_count}"
        embed.add_field(name="__Bot__", value=botinfo, inline=False)
        systeminfo = f"**<:python:879586023116529715> Python Version:** {sys.version.split()[0]}\n**<:discordpy:879586265014607893> Disnake Version:** {disnake.__version__}\n**<:microprocessor:879591544070488074> Process Memory Usage:** {psutil.Process(getpid()).memory_info().rss/1048576:.2f}MB"
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
    async def eval(self, ctx: ApplicationCustomContext, command: str = commands.Param(autocomplete=eval_autocomplete), respond: bool = True, show_all: bool = False):
        command = command.split(":")[0]
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

    # End general commands. Begin streamer commands

    ##########################################################

    # Autocompleters
    async def twitch_streamertitles_autocomplete(ctx: ApplicationCustomContext, user_input: str):
        callbacks = await ctx.bot.db.get_all_title_callbacks()
        return [alert_info['display_name'] for alert_info in callbacks.values() if str(ctx.guild.id) in alert_info['alert_roles'].keys() and alert_info['display_name'].lower().startswith(user_input)][:25]

    async def youtube_streamer_autocomplete(ctx: ApplicationCustomContext, user_input: str):
        callbacks = await ctx.bot.db.get_all_yt_callbacks()
        return [alert_info['display_name'] for alert_info in callbacks.values() if str(ctx.guild.id) in alert_info['alert_roles'].keys() and alert_info['display_name'].lower().startswith(user_input)][:25]

    async def twitch_streamer_autocomplete(ctx: ApplicationCustomContext, user_input: str):
        callbacks = await ctx.bot.db.get_all_callbacks()
        return [alert_info['display_name'] for alert_info in callbacks.values() if str(ctx.guild.id) in alert_info['alert_roles'].keys() and alert_info['display_name'].lower().startswith(user_input)][:25]

    ##########################################################

    @commands.slash_command()
    @has_manage_permissions()
    async def streamers(self, ctx: ApplicationCustomContext):
        pass

    @streamers.sub_command_group(name="add")
    async def streamers_add(self, ctx: ApplicationCustomContext):
        pass

    @streamers_add.sub_command(name="mode_zero", description="Dynamic notification + Temporary live status channel for a channel")
    async def streamers_add_mode_0(self, ctx: ApplicationCustomContext, platform: PlatformChoice, streamer_name_or_id: str,
                                   notification_channel: TextChannel, alert_role: Role = None, custom_live_message: str = None,
                                   allow_youtube_premieres: bool = commands.Param(default=False, description="Youtube Only: Allow premieres to trigger alerts")):
        if platform == PlatformChoice.Twitch:
            return await self.addstreamer_twitch(ctx, streamer_name_or_id, notification_channel, alert_role=alert_role,
                custom_live_message=custom_live_message, mode=0)
        elif platform == PlatformChoice.Youtube:
            return await self.addstreamer_youtube(ctx, streamer_name_or_id, notification_channel, alert_role=alert_role,
                custom_live_message=custom_live_message, allow_youtube_premieres=allow_youtube_premieres, mode=0)
        return await ctx.send(f"{self.bot.emotes.error} Invalid platform choice", ephemeral=True)

    @streamers_add.sub_command(name="mode_one", description="Only sends a dynamic live notification for a live stream")
    async def streamers_add_mode_1(self, ctx: ApplicationCustomContext, platform: PlatformChoice, streamer_name_or_id: str,
                                   notification_channel: TextChannel, alert_role: Role = None, custom_live_message: str = None,
                                   allow_youtube_premieres: bool = commands.Param(default=False, description="Youtube Only: Allow premieres to trigger alerts")):
        if platform == PlatformChoice.Twitch:
            return await self.addstreamer_twitch(ctx, streamer_name_or_id, notification_channel, alert_role=alert_role,
                custom_live_message=custom_live_message, mode=1)
        elif platform == PlatformChoice.Youtube:
            return await self.addstreamer_youtube(ctx, streamer_name_or_id, notification_channel, alert_role=alert_role,
            custom_live_message=custom_live_message, allow_youtube_premieres=allow_youtube_premieres, mode=1)
        return await ctx.send(f"{self.bot.emotes.error} Invalid platform choice", ephemeral=True)

    @streamers_add.sub_command(name="mode_two", description="Dynamic live notification + Persistent text channel reporting channel live status")
    async def streamers_add_mode_2(self, ctx: ApplicationCustomContext, platform: PlatformChoice, streamer_name_or_id: str,
                                   notification_channel: TextChannel, status_channel: TextChannel, alert_role: Role = None, custom_live_message: str = None,
                                   allow_youtube_premieres: bool = commands.Param(default=False, description="Youtube Only: Allow premieres to trigger alerts")):
        if platform == PlatformChoice.Twitch:
            return await self.addstreamer_twitch(ctx, streamer_name_or_id, notification_channel, alert_role=alert_role,
                status_channel=status_channel, custom_live_message=custom_live_message, mode=2)
        elif platform == PlatformChoice.Youtube:
            return await self.addstreamer_youtube(ctx, streamer_name_or_id, notification_channel, alert_role=alert_role, 
                status_channel=status_channel, custom_live_message=custom_live_message, allow_youtube_premieres=allow_youtube_premieres, mode=2)
        return await ctx.send(f"{self.bot.emotes.error} Invalid platform choice", ephemeral=True)

    async def addstreamer_twitch(self, ctx: ApplicationCustomContext, streamer_username: str,
                                 notification_channel: TextChannel, mode: int, alert_role: Role = None,
                                 status_channel: TextChannel = None, custom_live_message: str = None):
        # Run checks on all the supplied arguments
        streamer = await self.bot.tapi.get_user(user_login=streamer_username)
        if not streamer:
            streamer = await self.bot.tapi.get_user(user_id=streamer_username)
            if not streamer:
                raise commands.BadArgument(
                    f"Could not locate twitch channel {streamer_username}!")
        check_channel_permissions(ctx, channel=notification_channel)
        if status_channel is not None:
            check_channel_permissions(ctx, channel=status_channel)

        if custom_live_message:
            if len(custom_live_message) > 300:
                raise commands.UserInputError(
                    f"No more than 300 characters allowed for custom live message")

        # Checks done

        # Create file structure and subscriptions if necessary
        callback = await self.bot.db.get_callback(streamer) or {}
        if callback.get("alert_roles", {}).get(str(ctx.guild.id), None):
            view = Confirm(ctx)
            await ctx.response.send_message(f"{streamer.display_name} is already setup for this server! Do you want to override the current settings?", view=view)
            await view.wait()
            if view.value == False or view.value == None:
                for button in view.children:
                    button.disabled = True
                if view.value == False:
                    await view.interaction.response.edit_message(content=f"Aborting override", view=view)
                elif view.value == None:
                    await ctx.edit_original_message(content=f"Aborting override", view=view)
                return
            else:
                for button in view.children:
                    button.disabled = True
                await view.interaction.response.edit_message(view=view)

        make_subscriptions = False
        if callback == {}:
            make_subscriptions = True
            callback = {"display_name": streamer.display_name,
                        "alert_roles": {}}
            # Check title updates callback if it already has a title changes subscription
            title_callback = await self.bot.db.get_title_callback(streamer)
            if title_callback:
                callback["secret"] = title_callback["secret"]
                callback["title_id"] = title_callback["subscription_id"]
                del title_callback["subscription_id"]
                del title_callback["secret"]
                await self.bot.db.write_title_callback(streamer, title_callback)
            else:
                callback["secret"] = self.bot.random_string_generator(21)

        callback["alert_roles"][str(ctx.guild.id)] = {
            "mode": mode, "notif_channel_id": notification_channel.id}
        if alert_role == None:
            callback["alert_roles"][str(
                ctx.guild.id)]["role_id"] = None
        elif alert_role == ctx.guild.default_role:
            callback["alert_roles"][str(
                ctx.guild.id)]["role_id"] = "everyone"
        elif isinstance(alert_role, Role):
            callback["alert_roles"][str(
                ctx.guild.id)]["role_id"] = alert_role.id
        if mode == 2:
            callback["alert_roles"][str(
                ctx.guild.id)]["channel_id"] = status_channel.id
        if custom_live_message:
            callback["alert_roles"][str(
                ctx.guild.id)]["custom_message"] = custom_live_message

        await self.bot.db.write_callback(streamer, callback)

        if make_subscriptions:
            if not ctx.response.is_done():
                await ctx.response.defer()
            try:
                sub1 = await self.bot.tapi.create_subscription(SubscriptionType.STREAM_ONLINE, streamer=streamer, secret=callback["secret"], alert_type=AlertType.status)
                callback["online_id"] = sub1.id
                sub2 = await self.bot.tapi.create_subscription(SubscriptionType.STREAM_OFFLINE, streamer=streamer, secret=callback["secret"], alert_type=AlertType.status)
                callback["offline_id"] = sub2.id
                # Don't create a title updates subscription if we can take it from title updates callback
                if callback.get("title_id", None) is None:
                    sub3 = await self.bot.tapi.create_subscription(SubscriptionType.CHANNEL_UPDATE, streamer=streamer, secret=callback["secret"], alert_type=AlertType.title)
                    callback["title_id"] = sub3.id
            except SubscriptionError as e:
                await self.twitch_callback_deletion(ctx, streamer, callback, alert_type=AlertType.status)
                raise SubscriptionError(str(e))

        await self.bot.db.write_callback(streamer, callback)

        # Run catchup on streamer immediately
        stream = await self.bot.tapi.get_stream(streamer, origin=AlertOrigin.catchup)
        if stream:
            self.bot.queue.put_nowait(stream)
        else:
            streamer.origin = AlertOrigin.catchup
            if status_channel is not None:
                await status_channel.edit(name="stream-offline")
            self.bot.queue.put_nowait(streamer)            

        embed = Embed(title="Successfully added new streamer",
                      color=self.bot.colour)
        embed.add_field(name="Channel Name", value=streamer.display_name, inline=True)
        embed.add_field(name="Notification Channel",
                        value=notification_channel.mention, inline=True)
        if alert_role:
            embed.add_field(name="Alert Role", value=alert_role, inline=True)
        embed.add_field(name="Alert Mode", value=mode, inline=True)
        if mode == 2:
            embed.add_field(name="Status Channel",
                            value=status_channel.mention, inline=True)
        if custom_live_message:
            embed.add_field(name="Custom Alert Message",
                            value=custom_live_message, inline=False)
        await ctx.send(embed=embed)

    async def addstreamer_youtube(self, ctx: ApplicationCustomContext, channel_id_or_handle_or_display_name: str,
                                  notification_channel: TextChannel, mode: int, alert_role: Role = None,
                                  status_channel: TextChannel = None, custom_live_message: str = None, allow_youtube_premieres: bool = False):

        # Find account first
        # Assume display name first, saves an api request
        channel = (await self.bot.yapi.get_user(user_id=channel_id_or_handle_or_display_name)
                   or await self.bot.yapi.get_user(handle=channel_id_or_handle_or_display_name) 
                   or await self.bot.yapi.get_user(display_name=channel_id_or_handle_or_display_name)
                   or await self.bot.yapi.get_user(user_name=channel_id_or_handle_or_display_name))
        if channel is None:
            return await ctx.send(f"{self.bot.emotes.error} Failed to locate channel. You must provide either a channel ID (Starts with UC), a handle (starts with @) or a display name (somewhat unreliable)")

        # Run checks
        check_channel_permissions(ctx, channel=notification_channel)
        if status_channel is not None:
            check_channel_permissions(ctx, channel=status_channel)

        if isinstance(notification_channel, int):
            notification_channel = self.bot.get_channel(notification_channel)
        if isinstance(status_channel, int):
            status_channel = self.bot.get_channel(status_channel)

        if custom_live_message:
            if len(custom_live_message) > 300:
                raise commands.UserInputError(
                    f"No more than 300 characters allowed for custom live message")

        # Checks done

        # Create file structure and subscriptions if necessary
        callback = await self.bot.db.get_yt_callback(channel) or {}
        if callback.get("alert_roles", {}).get(str(ctx.guild.id), None):
            view = Confirm(ctx)
            await ctx.response.send_message(f"{channel.display_name} is already setup for this server! Do you want to override the current settings?", view=view)
            await view.wait()
            if view.value == False or view.value == None:
                for button in view.children:
                    button.disabled = True
                if view.value == False:
                    await view.interaction.response.edit_message(content=f"Aborting override", view=view)
                elif view.value == None:
                    await ctx.edit_original_message(content=f"Aborting override", view=view)
                return
            else:
                for button in view.children:
                    button.disabled = True
                await view.interaction.response.edit_message(view=view)

        make_subscriptions = False
        if callback == {}:
            make_subscriptions = True
            callback = {"display_name": channel.display_name,
                        "secret": self.bot.random_string_generator(21), "alert_roles": {}}

        if uploads_playlist_id := await self.bot.yapi.get_channel_upload_playlist_id(channel):
            callback["uploads_playlist_id"] = uploads_playlist_id

        callback["alert_roles"][str(ctx.guild.id)] = {
            "mode": mode, "notif_channel_id": notification_channel.id}
        if alert_role == None:
            callback["alert_roles"][str(
                ctx.guild.id)]["role_id"] = None
        elif alert_role == ctx.guild.default_role:
            callback["alert_roles"][str(
                ctx.guild.id)]["role_id"] = "everyone"
        else:
            callback["alert_roles"][str(
                ctx.guild.id)]["role_id"] = alert_role.id
        if mode == 2:
            callback["alert_roles"][str(
                ctx.guild.id)]["channel_id"] = status_channel.id
        if custom_live_message:
            callback["alert_roles"][str(
                ctx.guild.id)]["custom_message"] = custom_live_message
        if allow_youtube_premieres:
            callback["alert_roles"][str(
                ctx.guild.id)]["enable_premieres"] = allow_youtube_premieres

        await self.bot.db.write_yt_callback(channel, callback)

        if make_subscriptions:
            if not ctx.response.is_done():
                await ctx.response.defer()
            try:
                sub = await self.bot.yapi.create_subscription(channel, callback["secret"])
                callback["subscription_id"] = sub.id
            except SubscriptionError as e:
                await self.youtube_callback_deletion(ctx, channel, callback)
                raise SubscriptionError(str(e))
            timestamp = datetime.utcnow().timestamp() + (LEASE_SECONDS - 86500)
            await self.bot.db.write_yt_callback_expiration(channel, timestamp)

        await self.bot.db.write_yt_callback(channel, callback)

        # Run catchup on streamer immediately
        if make_subscriptions:
            if video_id := await self.bot.yapi.is_channel_live(channel):
                video = await self.bot.yapi.get_stream(video_id, origin=AlertOrigin.catchup)
                self.bot.queue.put_nowait(video)
            else:
                channel.origin = AlertOrigin.catchup
                self.bot.queue.put_nowait(channel)

        embed = Embed(title="Successfully added new youtube channel",
                      color=self.bot.colour)
        embed.add_field(name="Channel Name", value=channel.display_name, inline=True)
        embed.add_field(name="Channel ID", value=channel.id, inline=True)
        embed.add_field(name="Notification Channel",
                        value=notification_channel.mention, inline=True)
        if alert_role:
            embed.add_field(name="Alert Role", value=alert_role, inline=True)
        embed.add_field(name="Alert Mode", value=mode, inline=True)
        if mode == 2:
            embed.add_field(name="Status Channel",
                            value=status_channel.mention, inline=True)
        if custom_live_message:
            embed.add_field(name="Custom Alert Message",
                            value=custom_live_message, inline=False)
        await ctx.send(embed=embed)

    @staticmethod
    def page_generator(ctx: ApplicationCustomContext, data: dict, sort_by: str, reverse: bool) -> list[str]:
        pages: list[str] = []
        page = [
            f"```nim\n{'Channel':15s} {'Last Live D/M/Y':16s} {'Alert Role':25s} {'Alert Channel':18s} Alert Mode"]
        # The lambda pases the 2 items as a tuple, read the alert_info and return display name

        def sorter(items):
            if type(items[1][sort_by]) == str:
                return items[1][sort_by].lower()
            return items[1][sort_by]

        def truncate(name: str, amount: int) -> str:
            if len(name) >= amount:
                return f"{name[:amount-3]}..."
            return name
        
        for streamer_id, alert_info in dict(sorted(data.items(), key=sorter, reverse=reverse)).items():
            if str(ctx.guild.id) in alert_info["alert_roles"].keys():
                info = alert_info["alert_roles"][str(ctx.guild.id)]

                # Role Name
                alert_role_id = info.get("role_id", None)
                if alert_role_id is None:
                    alert_role = "<No Alert Role>"
                elif alert_role_id == "everyone":
                    alert_role == "@everyone"
                else:
                    if alert_role := ctx.guild.get_role(int(alert_role_id)):
                        alert_role = alert_role.name
                    else:
                        alert_role = "@deleted-role"

                # Channel
                channel_override_id = info.get("notif_channel_id", None)
                channel_override_role = ctx.guild.get_channel(
                    channel_override_id)
                if channel_override_role is not None:
                    channel_override = "#" + channel_override_role.name
                else:
                    channel_override = ""

                # Last Live
                last_live = alert_info["last_live"]
                if last_live == 0:
                    last_live = "Unknown"
                else:
                    last_live = datetime.utcfromtimestamp(
                        last_live).strftime("%d-%m-%y %H:%M")

                # If premieres enabled, youtube only
                if info.get("enable_premieres", False):
                    premieres = " + Premieres"
                else:
                    premieres = ""

                new_page_string = f"{truncate(alert_info['display_name'], 15):15s} {last_live:16s} {alert_role:25s} {channel_override:18s} {READABLE_MODES[info['mode']]}{premieres}"

                # Add page
                # Check if current page length + added string are near character limit. If so, start a new page.
                if sum(len(p) for p in page) + len(new_page_string) > 1980 or len(page) > 13:
                    if pages == []: # If this is the first page
                        pages.append(
                            '\n'.join(page[:-1] + [page[-1] + "```"]))
                    else:
                        pages.append(
                            '\n'.join(["```nim\n"] + page[:-1] + [page[-1] + "```"]))
                    page = [new_page_string]
                else:
                    page.append(new_page_string)

        if page != []:
            page = page[:-1] + [page[-1] + "```"]
            if pages == []:
                pages.append('\n'.join(page))
            else:
                pages.append('\n'.join(["```nim\n"] + page))
        return pages

    @streamers.sub_command_group(name="list")
    async def streamers_list(self, ctx: ApplicationCustomContext):
        pass

    @streamers_list.sub_command(name="twitch", description="List all the active streamer alerts setup in this server")
    async def streamers_list_twitch(self, ctx: ApplicationCustomContext):
        await ctx.response.defer()
        await self.bot.wait_until_db_ready()
        callbacks = await self.bot.db.get_all_callbacks()

        if len(callbacks) == 0:
            return await ctx.send(f"{self.bot.emotes.error} No streamers configured for this server!")
        for streamer_id, alert_info in dict(callbacks).items():
            cache = await self.bot.db.get_channel_cache(PartialUser(streamer_id, alert_info["display_name"].lower(), alert_info["display_name"]))
            callbacks[streamer_id]["last_live"] = cache.get(
                "alert_cooldown", 0)
        view = SortableTextPaginator(ctx, callbacks, self.page_generator, sorting_options={
                                     "display_name": 0, "last_live": 1}, show_delete=True)
        await ctx.send(content=view.pages[0], view=view)

    @streamers_list.sub_command(name="youtube", description="List all active youtube streamer alerts setup in this server")
    async def streamers_list_youtube(self, ctx: ApplicationCustomContext):
        await ctx.response.defer()
        await self.bot.wait_until_db_ready()
        callbacks = await self.bot.db.get_all_yt_callbacks()

        if len(callbacks) == 0:
            return await ctx.send(f"{self.bot.emotes.error} No streamers configured for this server!")
        for streamer, alert_info in dict(callbacks).items():
            cache = await self.bot.db.get_yt_channel_cache(streamer)
            callbacks[streamer]["last_live"] = cache.get(
                "alert_cooldown", 0)
        view = SortableTextPaginator(ctx, callbacks, self.page_generator, sorting_options={
                                     "display_name": 0, "last_live": 1}, show_delete=True)
        await ctx.send(content=view.pages[0], view=view)

    @streamers.sub_command_group(name="delete")
    async def streamers_delete(self, ctx: ApplicationCustomContext):
        pass

    @streamers_delete.sub_command(name="twitch", description="Remove live alerts for a twitch streamer")
    async def streamers_delete_twitch(self, ctx: ApplicationCustomContext, streamer: str = commands.Param(autocomplete=twitch_streamer_autocomplete)):
        await ctx.response.defer()
        await self.bot.wait_until_db_ready()
        streamer_obj = await self.bot.tapi.get_user(user_login=streamer)
        channel_cache = await self.bot.db.get_channel_cache(streamer_obj)
        callback = await self.bot.db.get_callback(streamer_obj)
        for channel_id in channel_cache.get("live_channels", []):
            channel = self.bot.get_channel(channel_id)
            if channel:
                if channel.guild == ctx.guild:
                    try:
                        if callback.alert_roles[str(channel.guild.id)].mode == 0:
                            await channel.delete()
                        # elif callbacks[streamer]["alert_roles"][str(channel.guild.id)]["mode"] == 2:
                        #     await channel.edit(name="stream-offline")
                    except disnake.Forbidden:
                        continue
                    except disnake.HTTPException:
                        continue
        await self.twitch_callback_deletion(ctx, streamer_obj, callback, alert_type=AlertType.status)
        await ctx.send(f"{self.bot.emotes.success} Deleted live alerts for {streamer}")

    @streamers_delete.sub_command(name="youtube", description="Remove live alerts for a youtube channel")
    async def streamers_delete_youtube(self, ctx: ApplicationCustomContext, channel_id_or_display_name: str = commands.Param(autocomplete=youtube_streamer_autocomplete)):
        await ctx.response.defer()
        await self.bot.wait_until_db_ready()
        callbacks = await self.bot.db.get_all_yt_callbacks()
        try:
            channel = [c for c in callbacks.keys() if c.display_name ==
                       channel_id_or_display_name][0]
        except IndexError:  # Try others if they're somehow valid
            channel = await self.bot.yapi.get_user(user_id=channel_id_or_display_name)
        if channel is None:
            channel = await self.bot.yapi.get_user(display_name=channel_id_or_display_name)
        if channel is None:
            return await ctx.send(f"{self.bot.emotes.error} Failed to locate channel")

        channel_cache = await self.bot.db.get_yt_channel_cache(channel)
        callback = await self.bot.db.get_yt_callback(channel)
        for channel_id in channel_cache.get("live_channels", []):
            if c := self.bot.get_channel(channel_id):
                if c.guild == ctx.guild:
                    try:
                        if callback["alert_roles"][str(c.guild.id)]["mode"] == 0:
                            await c.delete()
                        # elif callbacks[streamer]["alert_roles"][str(channel.guild.id)]["mode"] == 2:
                        #     await channel.edit(name="stream-offline")
                    except disnake.Forbidden:
                        continue
                    except disnake.HTTPException:
                        continue
        await self.youtube_callback_deletion(ctx, channel, callback)
        await ctx.send(f"{self.bot.emotes.success} Deleted live alerts for {channel.display_name}")

    ##########################################################

    @commands.slash_command(name="titlechanges")
    @has_manage_permissions()
    async def titlechanges_group(self, ctx: ApplicationCustomContext):
        pass

    @titlechanges_group.sub_command_group(name="add")
    async def titlechanges_add(self, ctx: ApplicationCustomContext):
        pass

    @titlechanges_add.sub_command(name="twitch", description="Add title change alerts for the provided streamer")
    async def titlechanges_add_twitch(self, ctx: ApplicationCustomContext, streamer_username: str, notification_channel: TextChannel, alert_role: Role = None):
        # Run checks on all the supplied arguments
        streamer = await self.bot.tapi.get_user(user_login=streamer_username)
        if not streamer:
            raise commands.BadArgument(
                f"Could not find twitch user {streamer_username}!")

        check_channel_permissions(ctx, channel=notification_channel)

        # Checks done
        if isinstance(notification_channel, int):
            notification_channel = self.bot.get_channel(notification_channel)

        # Create file structure and subscriptions if necessary
        title_callback = await self.bot.db.get_title_callback(streamer) or {}
        if title_callback.get("alert_roles", {}).get(str(ctx.guild.id), None):
            view = Confirm(ctx)
            await ctx.response.send_message(f"{streamer.display_name} is already setup for this server! Do you want to override the current settings?", view=view)
            await view.wait()
            if view.value == False or view.value == None:
                for button in view.children:
                    button.disabled = True
                if view.value == False:
                    await view.interaction.response.edit_message(content=f"Aborting override", view=view)
                elif view.value == None:
                    await ctx.edit_original_message(content=f"Aborting override", view=view)
                return
            else:
                for button in view.children:
                    button.disabled = True
                await view.interaction.response.edit_message(view=view)

        if title_callback == {}:
            title_callback = {
                "display_name": streamer.display_name, "alert_roles": {}}

        title_callback["alert_roles"][str(ctx.guild.id)] = {
            "notif_channel_id": notification_channel.id}
        if alert_role == None:
            title_callback["alert_roles"][str(
                ctx.guild.id)]["role_id"] = None
        elif alert_role == ctx.guild.default_role:
            title_callback["alert_roles"][str(
                ctx.guild.id)]["role_id"] = "everyone"
        else:
            title_callback["alert_roles"][str(
                ctx.guild.id)]["role_id"] = alert_role.id

        if await self.bot.db.get_callback(streamer) is None:
            title_callback["secret"] = self.bot.random_string_generator(21)
            await self.bot.db.write_title_callback(streamer, title_callback)
            if not ctx.response.is_done():
                await ctx.response.defer()
            try:
                sub = await self.bot.tapi.create_subscription(SubscriptionType.CHANNEL_UPDATE, streamer=streamer, secret=title_callback["secret"], alert_type=AlertType.title)
                title_callback["subscription_id"] = sub.id
            except SubscriptionError as e:
                await self.twitch_callback_deletion(ctx, streamer, title_callback, alert_type=AlertType.title)
                raise SubscriptionError(str(e))

        await self.bot.db.write_title_callback(streamer, title_callback)

        embed = Embed(
            title="Successfully added new title change alert", color=self.bot.colour)
        embed.add_field(name="Channel Name", value=streamer.display_name, inline=True)
        embed.add_field(name="Notification Channel",
                        value=notification_channel.mention, inline=True)
        embed.add_field(name="Alert Role", value=alert_role, inline=True)
        await ctx.send(embed=embed)

    @titlechanges_group.sub_command_group(name="delete")
    async def titlechanges_delete(self, ctx: ApplicationCustomContext):
        pass

    @titlechanges_delete.sub_command(name="twitch", description="Remove title change alerts for a twitch streamer")
    async def titlechanges_delete_twitch(self, ctx: ApplicationCustomContext, streamer: str = commands.Param(autocomplete=twitch_streamertitles_autocomplete)):
        await ctx.response.defer()
        streamer_obj = await self.bot.tapi.get_user(user_login=streamer)
        await self.twitch_callback_deletion(ctx, streamer_obj, alert_type=AlertType.title)
        await ctx.send(f"{self.bot.emotes.success} Deleted title change alert for {streamer}")

    @titlechanges_group.sub_command_group(name="list")
    async def titlechanges_list(self, ctx: ApplicationCustomContext):
        pass

    @titlechanges_list.sub_command(name="twitch", description="List all the active title change alerts setup in this server")
    async def titlechanges_list_twitch(self, ctx: ApplicationCustomContext):
        await ctx.response.defer()
        title_callbacks = await self.bot.db.get_all_title_callbacks()

        if len(title_callbacks) == 0:
            return await ctx.send(f"{self.bot.emotes.error} No title changes configured for this server!")

        pages: list[str] = []
        page = [
            f"```nim\n{'Channel':15s} {'Alert Role':35s} {'Alert Channel':18s}"]
        for streamer_id, alert_info in dict(sorted(title_callbacks.items(), key=lambda x: x[0])).items():
            if str(ctx.guild.id) in alert_info["alert_roles"].keys():
                info = alert_info["alert_roles"][str(ctx.guild.id)]
                alert_role_id = info.get("role_id", None)
                if alert_role_id is None:
                    alert_role = "<No Alert Role>"
                elif alert_role_id == "everyone":
                    alert_role == "@everyone"
                else:
                    if alert_role := ctx.guild.get_role(int(alert_role_id)):
                        alert_role = alert_role.name
                    else:
                        alert_role = "@deleted-role"

                alert_channel_id = info.get("notif_channel_id", None)
                alert_channel = ctx.guild.get_channel(alert_channel_id)
                if alert_channel is not None:
                    alert_channel = "#" + alert_channel.name
                else:
                    alert_channel = ""

                page.append(
                    f"{alert_info['display_name']:15s} {alert_role:35s} {alert_channel:18s}")
                if len(page) == 14:
                    if pages == []:
                        pages.append('\n'.join(page[:-1] + [page[-1] + "```"]))
                    else:
                        pages.append(
                            '\n'.join(["```nim\n"] + page[:-1] + [page[-1] + "```"]))
                    page = []

        if page != []:
            if pages == []:
                pages.append('\n'.join(page[:-1] + [page[-1] + "```"]))
            else:
                pages.append('\n'.join(["```nim\n"] +
                             page[:-1] + [page[-1] + "```"]))
        view = TextPaginator(ctx, pages, show_delete=True)
        await ctx.send(content=view.pages[0], view=view)

    ##########################################################

    async def twitch_callback_deletion(self, ctx: ApplicationCustomContext, streamer: User, callback: Callback = None, alert_type: AlertType = AlertType.status):
        await self.bot.wait_until_db_ready()
        callback = munchify(callback or await self.bot.db.get_callback(streamer))
        if alert_type.name == "status":
            callback = await self.bot.db.get_callback(streamer)
        elif alert_type.name == "title":
            callback = await self.bot.db.get_title_callback(streamer)
        try:
            del callback.alert_roles[str(ctx.guild.id)]
        except KeyError:
            raise commands.BadArgument("Streamer not found for server")
        if callback.alert_roles == {}:
            self.bot.log.info(
                f"Twitch streamer {streamer.display_name} is no longer enrolled in any alerts, purging callbacks and cache")
            if alert_type == AlertType.status:
                try:
                    await self.bot.tapi.delete_subscription(callback.offline_id)
                    await self.bot.tapi.delete_subscription(callback.online_id)
                    # Hand off subscription to title callback if it is defined for the streamer
                    if title_callback := await self.bot.db.get_title_callback(streamer):
                        title_callback.subscription_id = callback.title_id
                        title_callback.secret = callback.secret
                        await self.bot.db.write_title_callback(streamer, title_callback)
                    else:
                        await self.bot.tapi.delete_subscription(callback.title_id)
                except KeyError:
                    pass
                except AttributeError:
                    pass
                await self.bot.db.delete_channel_cache(streamer)
            else:
                if callback.get("subscription_id", None):
                    await self.bot.tapi.delete_subscription(callback.subscription_id)
                await self.bot.db.delete_title_cache(streamer)
            if alert_type.name == "status":
                await self.bot.db.delete_callback(streamer)
            elif alert_type.name == "title":
                await self.bot.db.delete_title_callback(streamer)
        else:
            if alert_type.name == "status":
                await self.bot.db.write_callback(streamer, callback)
            elif alert_type.name == "title":
                await self.bot.db.write_title_callback(streamer, callback)

    async def youtube_callback_deletion(self, ctx: ApplicationCustomContext, channel: YoutubeUser, callback: YoutubeCallback = None):
        await self.bot.wait_until_db_ready()
        callback = munchify(callback or await self.bot.db.get_yt_callback(channel))
        try:
            del callback.alert_roles[str(ctx.guild.id)]
        except KeyError:
            raise commands.BadArgument("Streamer not found for server")
        if callback.alert_roles == {}:
            self.bot.log.info(
                f"Youtube channel {channel.display_name} is no longer enrolled in any alerts, purging callbacks and cache")
            try:
                await self.bot.yapi.delete_subscription(YoutubeSubscription(callback.subscription_id, channel, callback.secret))
            except KeyError:
                pass
            await self.bot.db.delete_yt_channel_cache(channel)
            await self.bot.db.delete_yt_callback(channel)
        else:
            await self.bot.db.write_yt_callback(channel, callback)

    ##########################################################

    @commands.slash_command()
    @commands.is_owner()
    async def resubscribe(self, ctx: ApplicationCustomContext):
        pass

    @resubscribe.sub_command(name="twitch", description="Owner Only: Resubscribe every setup twitch callback. Useful for domain changes")
    async def resubscribe_twitch(self, ctx: ApplicationCustomContext):
        await ctx.response.defer()
        self.bot.log.info("[Twitch] Running subscription recreation")
        all_subs = await self.bot.tapi.get_subscriptions()
        all_ids = [s.id for s in all_subs if s.type in [SubscriptionType.STREAM_ONLINE,
                                                        SubscriptionType.STREAM_OFFLINE, SubscriptionType.CHANNEL_UPDATE]]
        for subscription in all_subs:
            if subscription.type in [SubscriptionType.STREAM_ONLINE, SubscriptionType.STREAM_OFFLINE, SubscriptionType.CHANNEL_UPDATE]:
                await self.bot.tapi.delete_subscription(subscription.id)
        async for streamer, callback_info in self.bot.db.async_get_all_callbacks():
            await asyncio.sleep(0.2)
            if callback_info.get("online_id", None) is not None and callback_info.get("online_id", None) not in all_ids:
                self.bot.log.info(f"Deleting subscriptions for {streamer.display_name}")
                await self.bot.tapi.delete_subscription(callback_info["online_id"])
            self.bot.log.info(f"Re-creating subscriptions for {streamer.display_name}")
            if not callback_info.get("secret"):
                self.bot.log.warning(f"Generating secret for {streamer.display_name} (This shouldn't be happening!)")
                callback_info["secret"] = self.bot.random_string_generator(21)
                await self.bot.db.write_callback(streamer, callback_info)
            rj1 = await self.bot.tapi.create_subscription(SubscriptionType.STREAM_ONLINE, streamer=streamer, secret=callback_info["secret"], alert_type=AlertType.status)
            callback_info["online_id"] = rj1.id
            await asyncio.sleep(0.2)
            if callback_info.get("offline_id", None) is not None and callback_info.get("offline_id", None) not in all_ids:
                await self.bot.tapi.delete_subscription(callback_info["offline_id"])
            rj2 = await self.bot.tapi.create_subscription(SubscriptionType.STREAM_OFFLINE, streamer=streamer, secret=callback_info["secret"], alert_type=AlertType.status)
            callback_info["offline_id"] = rj2.id
            await asyncio.sleep(0.2)
            if callback_info.get("title_id", None) is not None and callback_info.get("title_id", None) not in all_ids:
                await self.bot.tapi.delete_subscription(callback_info["title_id"])
            rj3 = await self.bot.tapi.create_subscription(SubscriptionType.CHANNEL_UPDATE, streamer=streamer, secret=callback_info["secret"], alert_type=AlertType.title)
            callback_info["title_id"] = rj3.id
            await self.bot.db.write_callback(streamer, callback_info)

        await ctx.send(f"{self.bot.emotes.success} Recreated live subscriptions!")

    @resubscribe.sub_command(name="youtube", description="Owner Only: Resubscribe every setup youtube callback. Useful for domain changes")
    async def resubscribe_youtube(self, ctx: ApplicationCustomContext):
        await ctx.response.defer()
        self.bot.log.info("[Youtube] Running subscription recreation")
        for channel, channel_data in (await self.bot.db.get_all_yt_callbacks()).items():
            await self.bot.yapi.create_subscription(channel, channel_data["secret"], channel_data["subscription_id"])
            # Minus a day plus 100 seconds, ensures that the subscription never expires
            timestamp = datetime.utcnow().timestamp() + (LEASE_SECONDS - 86500)
            await self.bot.db.write_yt_callback_expiration(channel, timestamp)
            await asyncio.sleep(0.25)

        await ctx.send(f"{self.bot.emotes.success} Recreated live subscriptions!")

    @commands.slash_command(description="Get a youtube user/channel from their various unique identification. Only one option is required")
    async def getyoutubeuser(self, ctx: ApplicationCustomContext,
                             user_id: str = commands.Param(default=None, description="A string of randomly generated characters, like UCV6mNrW8CrmWtcxWfQXy11g."),
                             handle: str = commands.Param(default=None, description="Youtube's new username system, they typically start with an @"),
                             display_name: str = commands.Param(default=None, description="The actual name of a channel"),
                             username: str = commands.Param(default=None, description="Youtube's legacy system for usernames, only old channels have these")):
        await ctx.response.defer()
        if user_id:
            user = await self.bot.yapi.get_user(user_id=user_id)
        elif handle:
            user = await self.bot.yapi.get_user(handle=handle)
        elif display_name:
            user = await self.bot.yapi.get_user(display_name=display_name)
        elif username:
            user = await self.bot.yapi.get_user(username=username)
        else:
            return await ctx.send(f"{self.bot.emotes.error} You must enter one of the options!")

        embed = Embed(title="Youtube User Info",
                      timestamp=utcnow(), colour=self.bot.colour)
        embed.set_author(name=user.display_name, icon_url=user.avatar_url)
        embed.add_field(name="Display Name", value=user.display_name)
        embed.add_field(name="Channel ID", value=user.id)
        embed.add_field(name="Channel Description", value=user.description, inline=False)
        await ctx.send(embed=embed)

    @commands.slash_command(description="Fetches information on a twitch user. Only one option is required")
    async def gettwitchuser(self, ctx: ApplicationCustomContext,
                            username: str = commands.Param(default=None, description="A channels unique username"),
                            user_id: str = commands.Param(default=None, description="A channels randomly generate ID")):
        await ctx.response.defer()
        if username:
            user = await self.bot.tapi.get_user(user_login=username)
        elif user_id:
            user = await self.bot.tapi.get_user(user_id=user_id)
        else:
            return await ctx.send(f"{self.bot.emotes.error} You must enter one of the options!")
        if user is None:
            return await ctx.send(f"{self.bot.emotes.error} Could not find twitch user \"{username or user_id}\"")
        follow_count = await self.bot.tapi.get_user_follow_count(user)

        # Chat colour: colour=int(hex(int((json["chatColor"] or "#000000").replace("#", ""), 16)), 0)
        embed = Embed(title="Twitch User Info",
                      timestamp=utcnow(), colour=self.bot.colour)
        embed.set_author(
            name=user.display_name, icon_url=user.avatar)
        embed.set_thumbnail(url=user.avatar)
        embed.add_field(name="Username", value=user.username)
        embed.add_field(name="Display Name", value=user.display_name)
        embed.add_field(name="ID", value=user.id)
        embed.add_field(name="Account Created",
                        value=f"{DiscordTimezone(user.created_at.timestamp(), TimestampOptions.long_date_short_time)} ({human_timedelta(user.created_at, accuracy=3)})", inline=False)
        embed.add_field(name="Bio", value=user.description, inline=False)
        embed.add_field(name="Follow Count", value=follow_count)
        if user.view_count != 0:
            embed.add_field(name="View Count", value=user.view_count)
        embed.add_field(name="Broadcaster Type", value=user.broadcaster_type.name.title())
        if user.type != UserType.none:
            embed.add_field(name="User Type", value=user.type.name.title())
        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(CommandsCog(bot))
