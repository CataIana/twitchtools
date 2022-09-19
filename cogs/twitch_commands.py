import asyncio
from datetime import datetime
from typing import Callable, TypeVar

import disnake
from disnake import Embed, Role, TextChannel
from disnake.ext import commands

from main import TwitchCallBackBot
from twitchtools import (AlertOrigin, AlertType, ApplicationCustomContext,
                         Confirm, PartialUser, SubscriptionType, TextPaginator,
                         User)
from twitchtools.exceptions import SubscriptionError

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


class TwitchCommandsCog(commands.Cog, name="Twitch Commands Cog"):
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()

    async def check_channel_permissions(self, ctx: ApplicationCustomContext, channel: TextChannel):
        perms = {"view_channel": True,
                 "read_message_history": True, "send_messages": True}
        permissions = channel.permissions_for(ctx.guild.me)

        missing = [perm for perm, value in perms.items(
        ) if getattr(permissions, perm) != value]
        if not missing:
            return True

        raise commands.BotMissingPermissions(missing)

    @commands.slash_command(name="addstreamer", description="Add live alerts for the provided streamer")
    @has_manage_permissions()
    async def addstreamer_group(self, ctx: ApplicationCustomContext):
        pass

    @addstreamer_group.sub_command_group(name="mode")
    async def addstreamer_sub_group(self, ctx: ApplicationCustomContext):
        pass

    @addstreamer_sub_group.sub_command(name="zero", description="Creates a temporary live channel when the streamer goes live")
    async def addmode0(self, ctx: ApplicationCustomContext, streamer_username: str,
                       notification_channel: TextChannel, alert_role: Role = None, custom_live_message: str = None):
        await self.addstreamer(ctx, streamer_username, notification_channel, alert_role=alert_role, custom_live_message=custom_live_message, mode=0)

    @addstreamer_sub_group.sub_command(name="one", description="Only sends a notification when the streamer goes live")
    async def addmode1(self, ctx: ApplicationCustomContext, streamer_username: str,
                       notification_channel: TextChannel, alert_role: Role = None, custom_live_message: str = None):
        await self.addstreamer(ctx, streamer_username, notification_channel, alert_role=alert_role, custom_live_message=custom_live_message, mode=1)

    @addstreamer_sub_group.sub_command(name="two", description="Updates a persistent status channel when the streamer goes live and offline")
    async def addmode2(self, ctx: ApplicationCustomContext, streamer_username: str,
                       notification_channel: TextChannel, status_channel: TextChannel, alert_role: Role = None, custom_live_message: str = None):
        await self.addstreamer(ctx, streamer_username, notification_channel, alert_role=alert_role, status_channel=status_channel, custom_live_message=custom_live_message, mode=2)

    async def addstreamer(self, ctx: ApplicationCustomContext, streamer_username: str,
                          notification_channel: TextChannel, mode: int, alert_role: Role = None,
                          status_channel: TextChannel = None, custom_live_message: str = None):
        # Run checks on all the supplied arguments
        streamer = await self.bot.tapi.get_user(user_login=streamer_username)
        if not streamer:
            raise commands.BadArgument(
                f"Could not find twitch user {streamer_username}!")
        await self.check_channel_permissions(ctx, channel=notification_channel)
        if status_channel is not None:
            await self.check_channel_permissions(ctx, channel=status_channel)

        if custom_live_message:
            if len(custom_live_message) > 300:
                raise commands.UserInputError(
                    f"No more than 300 characters allowed for custom live message")

        # Checks done

        # Create file structure and subscriptions if necessary
        callback = await self.bot.db.get_callback(streamer) or {}
        if callback.get("alert_roles", {}).get(str(ctx.guild.id), None):
            view = Confirm(ctx)
            await ctx.response.send_message(f"{streamer.username} is already setup for this server! Do you want to override the current settings?", view=view)
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
                        "secret": self.bot.random_string_generator(21), "alert_roles": {}}

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
                sub3 = await self.bot.tapi.create_subscription(SubscriptionType.CHANNEL_UPDATE, streamer=streamer, secret=callback["secret"], alert_type=AlertType.title)
                callback["title_id"] = sub3.id
            except SubscriptionError as e:
                await self.callback_deletion(ctx, streamer, alert_type=AlertType.status)
                raise SubscriptionError(str(e))

        await self.bot.db.write_callback(streamer, callback)

        # Run catchup on streamer immediately
        stream_status = await self.bot.tapi.get_stream(streamer, origin=AlertOrigin.catchup)
        if stream_status is None:
            if status_channel is not None:
                await status_channel.edit(name="stream-offline")
            self.bot.queue.put_nowait(streamer)
            #self.bot.dispatch("streamer_offline", streamer)
        else:
            #self.bot.dispatch("streamer_online", stream_status)
            self.bot.queue.put_nowait(stream_status)

        embed = Embed(title="Successfully added new streamer",
                      color=self.bot.colour)
        embed.add_field(name="Streamer", value=streamer.username, inline=True)
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

    @commands.slash_command(description="List all the active streamer alerts setup in this server")
    @has_manage_permissions()
    async def liststreamers(self, ctx: ApplicationCustomContext):
        callbacks = await self.bot.db.get_all_callbacks()

        if len(callbacks) == 0:
            return await ctx.send(f"{self.bot.emotes.error} No streamers configured for this server!")

        await self.bot.wait_until_db_ready()

        pages: list[str] = []
        page = [
            f"```nim\n{'Channel':15s} {'Last Live D/M/Y':16s} {'Alert Role':25s} {'Alert Channel':18s} Alert Mode"]
        # The lambda pases the 2 items as a tuple, read the alert_info and return display name
        for streamer_id, alert_info in dict(sorted(callbacks.items(), key=lambda packed_items: packed_items[1]['display_name'].lower())).items():
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

                channel_override_id = info.get("notif_channel_id", None)
                channel_override_role = ctx.guild.get_channel(
                    channel_override_id)
                if channel_override_role is not None:
                    channel_override = "#" + channel_override_role.name
                else:
                    channel_override = ""

                cache = await self.bot.db.get_channel_cache(PartialUser(streamer_id, alert_info["display_name"].lower(), alert_info["display_name"]))
                last_live = cache.get("alert_cooldown", "Unknown")
                if type(last_live) == int:
                    last_live = datetime.utcfromtimestamp(
                        last_live).strftime("%d-%m-%y %H:%M")

                page.append(
                    f"{alert_info['display_name']:15s} {last_live:16s} {alert_role:25s} {channel_override:18s} {info.get('mode', 2)}")
                if len(page) == 14:
                    if pages == []:
                        pages.append('\n'.join(page[:-1] + [page[-1] + "```"]))
                    else:
                        pages.append(
                            '\n'.join(["```nim\n"] + page[:-1] + [page[-1] + "```"]))
                    page = []

        if page != []:
            page = page[:-1] + [page[-1] + "```"]
            if pages == []:
                pages.append('\n'.join(page))
            else:
                pages.append('\n'.join(["```nim\n"] + page))
        view = TextPaginator(ctx, pages, show_delete=True)
        await ctx.send(content=view.pages[0], view=view)

    @commands.slash_command(description="List all the active title change alerts setup in this server")
    @has_manage_permissions()
    async def listtitlechanges(self, ctx: ApplicationCustomContext):
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

    @commands.slash_command(description="Add title change alerts for the provided streamer")
    @has_manage_permissions()
    async def addtitlechange(self,
                             ctx: ApplicationCustomContext,
                             streamer_username: str,
                             notification_channel: TextChannel,
                             alert_role: Role = None
                             ):
        # Run checks on all the supplied arguments
        streamer = await self.bot.tapi.get_user(user_login=streamer_username)
        if not streamer:
            raise commands.BadArgument(
                f"Could not find twitch user {streamer_username}!")
        await self.check_channel_permissions(ctx, channel=notification_channel)

        # Checks done
        if isinstance(notification_channel, int):
            notification_channel = self.bot.get_channel(notification_channel)

        # Create file structure and subscriptions if necessary
        title_callback = await self.bot.db.get_title_callback(streamer)

        if title_callback is None:
            title_callback = {
                "channel_id": streamer.id, "alert_roles": {}}

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

        await self.bot.db.write_title_callback(streamer, title_callback)

        embed = Embed(
            title="Successfully added new title change alert", color=self.bot.colour)
        embed.add_field(name="Streamer", value=streamer.username, inline=True)
        embed.add_field(name="Notification Channel",
                        value=notification_channel.mention, inline=True)
        embed.add_field(name="Alert Role", value=alert_role, inline=True)
        await ctx.send(embed=embed)

    async def streamer_autocomplete(ctx: ApplicationCustomContext, user_input: str):
        callbacks = await ctx.bot.db.get_all_callbacks()
        return [alert_info['display_name'].lower() for alert_info in callbacks.values() if str(ctx.guild.id) in alert_info['alert_roles'].keys() and alert_info['display_name'].lower().startswith(user_input)][:25]

    @commands.slash_command()
    @has_manage_permissions()
    async def delstreamer(self, ctx: ApplicationCustomContext, streamer: str = commands.Param(autocomplete=streamer_autocomplete)):
        """
        Remove live alerts for a streamer
        """
        await self.bot.wait_until_db_ready()
        streamer_obj = await self.bot.tapi.get_user(user_login=streamer)
        channel_cache = await self.bot.db.get_channel_cache(streamer_obj)
        callback = await self.bot.db.get_callback(streamer_obj)
        for channel_id in channel_cache.get("live_channels", []):
            channel = self.bot.get_channel(channel_id)
            if channel:
                if channel.guild == ctx.guild:
                    try:
                        if callback["alert_roles"][str(channel.guild.id)]["mode"] == 0:
                            await channel.delete()
                        # elif callbacks[streamer]["alert_roles"][str(channel.guild.id)]["mode"] == 2:
                        #     await channel.edit(name="stream-offline")
                    except disnake.Forbidden:
                        continue
                    except disnake.HTTPException:
                        continue
        await self.callback_deletion(ctx, streamer_obj, alert_type=AlertType.status)
        await ctx.send(f"{self.bot.emotes.success} Deleted live alerts for {streamer}")

    async def streamertitles_autocomplete(ctx: ApplicationCustomContext, user_input: str):
        callbacks = await ctx.bot.db.get_all_title_callbacks()
        return [alert_info['display_name'].lower() for alert_info in callbacks.values() if str(ctx.guild.id) in alert_info['alert_roles'].keys() and alert_info['display_name'].lower().startswith(user_input)][:25]

    @commands.slash_command()
    @has_manage_permissions()
    async def deltitlechange(self, ctx: ApplicationCustomContext, streamer: str = commands.Param(autocomplete=streamertitles_autocomplete)):
        """
        Remove title change alerts for a streamer
        """
        streamer_obj = await self.bot.tapi.get_user(user_login=streamer)
        await self.callback_deletion(ctx, streamer_obj, alert_type=AlertType.title)
        await ctx.send(f"{self.bot.emotes.success} Deleted title change alert for {streamer}")

    async def callback_deletion(self, ctx: ApplicationCustomContext, streamer: User, alert_type: AlertType = AlertType.status):
        if alert_type.name == "status":
            callback = await self.bot.db.get_callback(streamer)
        elif alert_type.name == "title":
            callback = await self.bot.db.get_title_callback(streamer)
        try:
            del callback["alert_roles"][str(ctx.guild.id)]
        except KeyError:
            raise commands.BadArgument("Streamer not found for server")
        if callback["alert_roles"] == {}:
            self.bot.log.info(
                f"{streamer} is no longer enrolled in any alerts, purging callbacks and cache")
            await self.bot.wait_until_db_ready()
            if alert_type == AlertType.status:
                try:
                    await self.bot.tapi.delete_subscription(callback["offline_id"])
                    await self.bot.tapi.delete_subscription(callback["online_id"])
                    await self.bot.tapi.delete_subscription(callback["title_id"])
                except KeyError:
                    pass
                await self.bot.db.delete_channel_cache(streamer)
            else:
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

    @commands.slash_command(description="Owner Only: Resubscribe every setup callback. Useful for domain changes")
    @commands.is_owner()
    async def resubscribetwitch(self, ctx: ApplicationCustomContext):
        await ctx.response.defer()
        self.bot.log.info("Running twitch subscription resubscribe")
        all_subs = await self.bot.tapi.get_subscriptions()
        all_ids = [s.id for s in all_subs if s.type in [SubscriptionType.STREAM_ONLINE,
                                                        SubscriptionType.STREAM_OFFLINE, SubscriptionType.CHANNEL_UPDATE]]
        for subscription in all_subs:
            if subscription.type in [SubscriptionType.STREAM_ONLINE, SubscriptionType.STREAM_OFFLINE, SubscriptionType.CHANNEL_UPDATE]:
                await self.bot.tapi.delete_subscription(subscription.id)
        async for streamer, callback_info in self.bot.db.async_get_all_callbacks():
            await asyncio.sleep(0.2)
            if callback_info.get("online_id", None) is not None and callback_info.get("online_id", None) not in all_ids:
                await self.bot.tapi.delete_subscription(callback_info["online_id"])
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


def setup(bot):
    bot.add_cog(TwitchCommandsCog(bot))
