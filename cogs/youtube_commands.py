from asyncio import sleep
from datetime import datetime
from typing import Callable, TypeVar, Union

import disnake
from disnake import Embed, Role, TextChannel
from disnake.ext import commands, tasks

from main import TwitchCallBackBot
from twitchtools import (AlertOrigin, ApplicationCustomContext, Confirm,
                         TextPaginator, YoutubeSubscription, YoutubeUser)
from twitchtools.exceptions import SubscriptionError

T = TypeVar("T")
LEASE_SECONDS = 828000


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


class YoutubeCommandsCog(commands.Cog, name="Youtube Commands Cog"):
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()
        self.youtube_backup_checks.start()

    def cog_unload(self):
        self.youtube_backup_checks.cancel()

    @tasks.loop(seconds=300)
    async def youtube_backup_checks(self):
        await self.bot.youtube_catchup()
        self.bot.log.info("Ran youtube catchup")

    async def check_channel_permissions(self, ctx: ApplicationCustomContext, channel: TextChannel):
        perms = {"view_channel": True,
                 "read_message_history": True, "send_messages": True}
        permissions = channel.permissions_for(ctx.guild.me)

        missing = [perm for perm, value in perms.items(
        ) if getattr(permissions, perm) != value]
        if not missing:
            return True

        raise commands.BotMissingPermissions(missing)

    @commands.slash_command(name="addyoutubestreamer", description="Add live alerts for the provided youtube streamer")
    @has_manage_permissions()
    async def addyoutubestreamer_group(self, ctx: ApplicationCustomContext):
        pass

    @addyoutubestreamer_group.sub_command_group(name="mode")
    async def addyoutubestreamer_sub_group(self, ctx: ApplicationCustomContext):
        pass

    @addyoutubestreamer_sub_group.sub_command(name="zero", description="Creates a temporary live channel when the streamer goes live")
    async def addmode0(self, ctx: ApplicationCustomContext, channel_id_or_display_name: str,
                       notification_channel: TextChannel, alert_role: Role = None, custom_live_message: str = None):
        await self.addyoutubestreamer(ctx, channel_id_or_display_name, notification_channel, alert_role=alert_role, custom_live_message=custom_live_message, mode=0)

    @addyoutubestreamer_sub_group.sub_command(name="one", description="Only sends a notification when the streamer goes live")
    async def addmode1(self, ctx: ApplicationCustomContext, channel_id_or_display_name: str,
                       notification_channel: TextChannel, alert_role: Role = None, custom_live_message: str = None):
        await self.addyoutubestreamer(ctx, channel_id_or_display_name, notification_channel, alert_role=alert_role, custom_live_message=custom_live_message, mode=1)

    @addyoutubestreamer_sub_group.sub_command(name="two", description="Updates a persistent status channel when the streamer goes live and offline")
    async def addmode2(self, ctx: ApplicationCustomContext, channel_id_or_display_name: str,
                       notification_channel: TextChannel, status_channel: TextChannel, alert_role: Role = None, custom_live_message: str = None):
        await self.addyoutubestreamer(ctx, channel_id_or_display_name, notification_channel, alert_role=alert_role, status_channel=status_channel, custom_live_message=custom_live_message, mode=2)

    async def addyoutubestreamer(self, ctx: ApplicationCustomContext, channel_id_or_display_name: str,
                                 notification_channel: TextChannel, mode: int, alert_role: Role = None,
                                 status_channel: TextChannel = None, custom_live_message: str = None):

        # Find account first
        # Assume display name first, saves an api request
        channel = await self.bot.yapi.get_user(display_name=channel_id_or_display_name) or await self.bot.yapi.get_user(user_id=channel_id_or_display_name)
        if channel is None:
            return await ctx.send(f"{self.bot.emotes.error} Failed to locate channel")

        # Run checks
        await self.check_channel_permissions(ctx, channel=notification_channel)
        if status_channel is not None:
            await self.check_channel_permissions(ctx, channel=status_channel)

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

        await self.bot.db.write_yt_callback(channel, callback)

        if make_subscriptions:
            if not ctx.response.is_done():
                await ctx.response.defer()
            try:
                sub = await self.bot.yapi.create_subscription(channel, callback["secret"])
                callback["subscription_id"] = sub.id
            except SubscriptionError as e:
                await self.youtube_callback_deletion(ctx, channel)
                raise SubscriptionError(str(e))

        await self.bot.db.write_yt_callback(channel, callback)

        # Run catchup on streamer immediately
        if make_subscriptions:
            if video_id := await self.bot.yapi.is_channel_live(channel):
                video = await self.bot.yapi.get_stream(video_id, alert_origin=AlertOrigin.catchup)
                self.bot.queue.put_nowait(video)
            else:
                self.bot.queue.put_nowait(channel)

        embed = Embed(title="Successfully added new youtube channel",
                      color=self.bot.colour)
        embed.add_field(name="Channel",
                        value=channel.display_name, inline=True)
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

    @commands.slash_command(description="List all active youtube streamer alerts setup in this server")
    @has_manage_permissions()
    async def listyoutubestreamers(self, ctx: ApplicationCustomContext):
        callbacks = await self.bot.db.get_all_yt_callbacks()

        if len(callbacks) == 0:
            return await ctx.send(f"{self.bot.emotes.error} No streamers configured for this server!")

        await self.bot.wait_until_db_ready()

        pages: list[str] = []
        page = [
            f"```nim\n{'Channel':15s} {'Last Live D/M/Y':16s} {'Alert Role':25s} {'Alert Channel':18s} Alert Mode"]
        # The lambda pases the 2 items as a tuple, read the alert_info and return display name
        for channel, alert_info in dict(sorted(callbacks.items(), key=lambda packed_items: packed_items[1]['display_name'].lower())).items():
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
                channel_override = ctx.guild.get_channel(channel_override_id)
                if channel_override is not None:
                    channel_override = "#" + channel_override.name
                else:
                    channel_override = ""

                cache = await self.bot.db.get_yt_channel_cache(channel)
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

    async def yt_streamer_autocomplete(ctx: ApplicationCustomContext, user_input: str):
        callbacks = await ctx.bot.db.get_all_yt_callbacks()
        return [alert_info['display_name'] for alert_info in callbacks.values() if str(ctx.guild.id) in alert_info['alert_roles'].keys() and alert_info['display_name'].lower().startswith(user_input)][:25]

    @commands.slash_command(description="Remove live alerts for a youtube streamer")
    async def delyoutubestreamer(self, ctx: ApplicationCustomContext, channel_id_or_display_name: str = commands.Param(autocomplete=yt_streamer_autocomplete)):
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

        await self.bot.wait_until_db_ready()
        channel_cache = await self.bot.db.get_yt_channel_cache(channel)
        callback = await self.bot.db.get_yt_callback(channel)
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
        await self.youtube_callback_deletion(ctx, channel)
        await ctx.send(f"{self.bot.emotes.success} Deleted live alerts for {channel.display_name}")

    async def youtube_callback_deletion(self, ctx: ApplicationCustomContext, channel: YoutubeUser):
        callback = await self.bot.db.get_yt_callback(channel)
        try:
            del callback["alert_roles"][str(ctx.guild.id)]
        except KeyError:
            raise commands.BadArgument("Streamer not found for server")
        if callback["alert_roles"] == {}:
            self.bot.log.info(
                f"Youtube channel {channel.display_name} is no longer enrolled in any alerts, purging callbacks and cache")
            await self.bot.wait_until_db_ready()
            try:
                r = await self.bot.yapi.delete_subscription(YoutubeSubscription(callback["subscription_id"], channel, callback["secret"]))
            except KeyError:
                pass
            await self.bot.db.delete_yt_channel_cache(channel)
            await self.bot.db.delete_yt_callback(channel)
        else:
            await self.bot.db.write_yt_callback(channel, callback)

    @commands.slash_command(description="Owner Only: Resubscribe every setup callback. Useful for domain changes")
    @commands.is_owner()
    async def resubscribeyoutube(self, ctx: ApplicationCustomContext):
        await ctx.response.defer()
        self.bot.log.info("Running youtube subscription resubscribe")
        for channel, channel_data in (await self.bot.db.get_all_yt_callbacks()).items():
            await self.bot.yapi.create_subscription(channel, channel_data["secret"], channel_data["subscription_id"])
            # Minus a day plus 100 seconds, ensures that the subscription never expires
            timestamp = datetime.utcnow().timestamp() + (LEASE_SECONDS - 86500)
            await self.bot.db.write_yt_callback_expiration(channel, timestamp)
            self.bot.log.info(f"Resubscribed {channel.display_name}")
            await sleep(0.25)

        await ctx.send(f"{self.bot.emotes.success} Recreated live subscriptions!")


def setup(bot):
    bot.add_cog(YoutubeCommandsCog(bot))
