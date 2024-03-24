from datetime import timedelta
from time import time
from math import floor
from typing import TYPE_CHECKING, Union

import disnake
import aiofiles
from aiohttp import client_exceptions
from yaml import load, YAMLError
try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader
from dateutil import parser, tz
from disnake.ext import commands
from disnake.utils import utcnow

from twitchtools import (AlertOrigin, PartialUser, PartialYoutubeUser, Stream,
                         TitleEvent, User, YoutubeUser, YoutubeVideo,
                         YoutubeVideoType, human_timedelta, Callback, YoutubeCallback)
from twitchtools.enums import ChannelCache, YoutubeChannelCache

if TYPE_CHECKING:
    from main import TwitchCallBackBot

TWITCH_PURPLE = 9520895  # Hex #9146FF
YOUTUBE_RED = 16711680  # Hex FF0000


class StreamStateManager(commands.Cog):
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()
        self.ignore_cooldowns: bool = False  # Used for debugging/development
        self.footer_msg: str = "POGGIES"

    async def on_title_change(self, event: TitleEvent):
        await self.bot.wait_until_ready()
        await self.bot.wait_until_db_ready()
        title_callback = await self.bot.db.get_title_callback(event.broadcaster)
        title_cache = await self.bot.db.get_title_cache(event.broadcaster)
        old_title = title_cache.title  # Get cached information for streamer, or none
        old_game = title_cache.game

        updated = []  # Quick way to make the dynamic embed title
        if event.title != old_title:
            updated.append("title")
        if event.game != old_game:
            updated.append("game")

        if updated == []:  # If for some reason neither the title or game updated, just ignore
            return

        title_cache.title = event.title
        title_cache.game = event.game

        await self.bot.db.write_title_cache(event.broadcaster, title_cache)

        if stream := await self.bot.tapi.get_stream(event.broadcaster.username, origin=AlertOrigin.callback):
            return await self.title_change_update_alerts(event, stream, old_game)

        if not title_callback:
            return

        user = await self.bot.tapi.get_user(user_id=event.broadcaster.id)
        # Create embed for discord
        embed = disnake.Embed(
            url=f"https://twitch.tv/{event.broadcaster.username}", colour=TWITCH_PURPLE, timestamp=utcnow())
        if event.title != old_title:
            embed.add_field(name="Old Title", value=old_title, inline=True)
            embed.add_field(name="New Title", value=event.title, inline=True)
        if event.game != old_game:
            embed.add_field(name="Old Game", value=old_game, inline=True)
            embed.add_field(name="New Game", value=event.game, inline=True)
        embed.set_author(name=f"{event.broadcaster.display_name} updated their {' and '.join(updated)}!",
                         url=f"https://twitch.tv/{event.broadcaster.username}", icon_url=user.avatar)
        embed.set_footer(text=self.footer_msg)

        self.bot.log.info(
            f"[Twitch] {event.broadcaster.username} => TITLE UPDATE")

        # Send embed to each defined channel
        for alert_info in title_callback.alert_roles.values():
            if c := self.bot.get_channel(alert_info.notif_channel_id):
                if alert_info.role_id is None:
                    role_mention = ""
                elif alert_info.role_id == "everyone":
                    role_mention = "@everyone"
                else:
                    role_mention = f"<@&{alert_info.role_id}>"
                try:
                    await c.send(f"{role_mention}", embed=embed)
                except disnake.Forbidden:
                    pass
                except disnake.HTTPException:
                    pass

    async def on_streamer_offline(self, streamer: Union[User, PartialUser]):
        await self.bot.wait_until_ready()
        await self.bot.wait_until_db_ready()
        channel_cache = await self.bot.db.get_channel_cache(streamer)
        callback = await self.bot.db.get_callback(streamer)

        if not callback:
            return
        if not self.is_live(channel_cache):
            return

        self.bot.log.info(
            f"[Twitch]{self.is_catchup(streamer)} {streamer.display_name} => OFFLINE")

        await self.set_channels_offline(callback, channel_cache)
        await self.set_twitch_alerts_offline(streamer, callback, channel_cache)

        channel_cache.pop("live_channels", None)
        if channel_cache.get("live_alerts", []) != []:
            channel_cache.reusable_alerts = channel_cache.live_alerts
        channel_cache.pop("live_alerts", None)
        channel_cache.pop("stream_id", None)
        channel_cache.is_live = False
        channel_cache.pop("games", None)
        channel_cache.pop("last_update", None)
        channel_cache.pop("viewer_milestone", None)
        channel_cache.pop("triggered_guilds", None)

        # Update cache
        await self.bot.db.write_channel_cache(streamer, channel_cache)

    async def on_youtube_streamer_offline(self, channel: Union[YoutubeUser, PartialYoutubeUser]):
        await self.bot.wait_until_ready()
        await self.bot.wait_until_db_ready()
        # Due to lack of an event, only catchup will trigger this
        channel_cache = await self.bot.db.get_yt_channel_cache(channel)
        callback = await self.bot.db.get_yt_callback(channel)
        if not callback:
            return
        if not self.is_live(channel_cache):
            return
        self.bot.log.info(
            f"[Youtube]{self.is_catchup(channel)} {channel.display_name} => OFFLINE")
        await self.set_channels_offline(callback, channel_cache)
        await self.set_youtube_alerts_offline(channel, callback, channel_cache)

        channel_cache.pop("live_channels", None)
        if channel_cache.get("live_alerts", []) != []:
            channel_cache.reusable_alerts = channel_cache.live_alerts
        channel_cache.pop("live_alerts", None)
        channel_cache.pop("video_id", None)
        channel_cache.is_live = False
        channel_cache.pop("last_update", None)
        channel_cache.pop("triggered_guilds", None)

        # Update cache
        await self.bot.db.write_yt_channel_cache(channel, channel_cache)

    async def on_streamer_online(self, stream: Stream):
        await self.bot.wait_until_ready()
        await self.bot.wait_until_db_ready()

        channel_cache = await self.bot.db.get_channel_cache(stream.user)
        callback = await self.bot.db.get_callback(stream.user)
        on_cooldown = self.on_cooldown(channel_cache.get("alert_cooldown", 0))

        # Do not re-run this function is the streamer is already live
        if self.is_live(channel_cache):
            if stream.origin == AlertOrigin.callback:
                self.bot.log.info(
                    f"[Twitch] Callback received for {stream.user.display_name} while live, ignoring")
            elif stream.origin == AlertOrigin.catchup:
                await self.viewer_count_milestones(stream, callback, channel_cache)
            # Remove this return so that title phrase matching can run
            # return

        else:
            if on_cooldown:  # There is a 10 minute cooldown between alerts, but live channels will still be created
                self.bot.log.info(
                    f"[Twitch] Notification cooldown active for {stream.user.display_name}, restoring old channels/messages")

            self.bot.log.info(
                f"[Twitch]{self.is_catchup(stream)} {stream.user.display_name} => ONLINE")

        # If no guilds left to recheck, just return
        if [k for k in callback.alert_roles.keys() if k not in channel_cache.get("triggered_guilds", [])] == []:
            return

        # Update cached display name
        if callback.display_name != stream.user.display_name:
            callback.display_name = stream.user.display_name
            await self.bot.db.write_callback(stream.user, callback)

        # Create embed message
        stream.user = await self.bot.tapi.get_user(user=stream.user)
        embed = self.get_stream_embed(stream)

        live_channels, live_alerts, triggered_guilds = await self.send_live_alerts_and_channels(stream, embed, callback, channel_cache)

        if not channel_cache.get("is_live", False):
            # Finally, combine all data into channel cache, and update the file
            channel_cache = {
                "alert_cooldown": int(time()),
                "user_login": stream.user.username,
                "stream_id": stream.stream_id,
                "is_live": True,
                "live_channels": live_channels,
                "live_alerts": live_alerts,
                "last_update": int(time()),
                "games": {stream.game_name: 0},
                "triggered_guilds": triggered_guilds
            }
        else:
            channel_cache["triggered_guilds"] = list(
                set(triggered_guilds + channel_cache["triggered_guilds"]))
            channel_cache["live_channels"] = list(
                set(live_channels + channel_cache["live_channels"]))
            msgs = [a["message"] for a in channel_cache["live_alerts"]]
            for alert in live_alerts:
                if alert["message"] not in msgs:
                    channel_cache["live_alerts"].append(alert)

        # await write_channel_cache(channel_cache)
        await self.bot.db.write_channel_cache(stream.user, channel_cache)

    async def on_youtube_streamer_online(self, video: YoutubeVideo):
        await self.bot.wait_until_ready()
        await self.bot.wait_until_db_ready()

        # Ignore these for now
        if video.type in [YoutubeVideoType.scheduled_premiere, YoutubeVideoType.scheduled_stream]:
            return

        channel_cache = await self.bot.db.get_yt_channel_cache(video.channel)
        callback = await self.bot.db.get_yt_callback(video.channel)
        on_cooldown = self.on_cooldown(channel_cache.get("alert_cooldown", 0))

        # Update title details if streamer is already live
        if self.is_live(channel_cache):
            if video.origin == AlertOrigin.catchup:
                await self.update_youtube_title(video, channel_cache)
            elif video.origin == AlertOrigin.callback:
                self.bot.log.info(f"[Youtube] Callback received for {video.user.display_name} while live, ignoring")
            return

        if on_cooldown:  # There is a 10 minute cooldown between alerts, but live channels will still be created
            self.bot.log.info(
                f"[Youtube] Notification cooldown active for {video.user.display_name}, restoring old channels/messages")

        self.bot.log.info(
            f"[Youtube{' Premiere' if video.type == YoutubeVideoType.premiere else ' Stream'}]{self.is_catchup(video)} {video.user.display_name} => ONLINE")

        # Update cached display name
        if callback.display_name != video.user.display_name:
            callback.display_name = video.user.display_name
            await self.bot.db.write_yt_callback(video.user, callback)

        # Create embed message
        video.user = await self.bot.yapi.get_user(video.user)
        embed = self.get_stream_embed(video)

        live_channels, live_alerts, triggered_guilds = await self.send_live_alerts_and_channels(video, embed, callback, channel_cache)

        if not channel_cache.get("is_live", False):
            # Finally, combine all data into channel cache, and update the file
            channel_cache = {
                "alert_cooldown": int(time()),
                "channel_id": video.channel.id,
                "video_id": video.id,
                "is_live": True,
                "live_channels": live_channels,
                "live_alerts": live_alerts,
                "last_update": int(time()),
                "triggered_guilds": triggered_guilds
            }
        else:
            channel_cache["triggered_guilds"] = list(
                set(triggered_guilds + channel_cache["triggered_guilds"]))
            channel_cache["live_channels"] = list(
                set(live_channels + channel_cache["live_channels"]))
            msgs = [a["message"] for a in channel_cache["live_alerts"]]
            for alert in live_alerts:
                if alert["message"] not in msgs:
                    channel_cache["live_alerts"].append(alert)

        # await write_channel_cache(channel_cache)
        await self.bot.db.write_yt_channel_cache(video.user, channel_cache)

    def on_cooldown(self, alert_cooldown: int) -> bool:
        if int(time()) - alert_cooldown < 1800 and not self.ignore_cooldowns:
            return True
        return False

    def is_live(self, channel_cache: Union[ChannelCache, YoutubeChannelCache]) -> bool:
        # To reduce the likelyhood of strange errors, clarify this.
        if channel_cache.get("is_live", False):
            return True

    async def send_live_alerts_and_channels(self, item: Union[Stream, YoutubeVideo], embed: disnake.Embed, callback: Union[Callback, YoutubeCallback], channel_cache: Union[ChannelCache, YoutubeChannelCache]) -> tuple[list, list, list]:
        SelfOverride, DefaultRole, OverrideRole = self.get_overwrites()
        on_cooldown = self.on_cooldown(channel_cache.get("alert_cooldown", 0))

        live_channels = []
        live_alerts = []
        triggered_guilds = []
        reuse_done = False
        for guild_id, alert_info in {k: v for k, v in callback.alert_roles.items() if k not in channel_cache.get("triggered_guilds", [])}.items():
            guild = self.bot.get_guild(int(guild_id))
            if guild is None:
                continue

            if alert_info.get("title_match_phrase", None):
                if alert_info.title_match_phrase not in item.title.lower():
                    self.bot.log.info(
                        f"{'[Youtube]' if isinstance(item, YoutubeVideo) else '[Twitch]'} {item.user.display_name} title phrase for {guild.name} didn't match, skipping alert")
                    continue

            user_escaped = item.user.display_name.replace('_', '\_')

            if isinstance(item, YoutubeVideo):
                if item.type == YoutubeVideoType.premiere and not alert_info.enable_premieres:
                    continue
                message = f"{user_escaped} is live on Youtube!"
                link = f"https://youtube.com/watch?v={item.id}"
            else:
                message = f"{user_escaped} is live on Twitch!"
                link = f"https://twitch.tv/{item.user.username}"

            # Format role mention
            if alert_info.role_id == "everyone":
                role_mention = f" {guild.default_role}"
            elif alert_info.role_id == None:
                role_mention = ""
            else:
                role = guild.get_role(alert_info.role_id)
                role_mention = f" {role.mention}"

            if not on_cooldown:  # Send live alert if not on alert cooldown, and append channel id and message id to channel cache
                alert_channel_id = alert_info.get("notif_channel_id", None)
                alert_channel = self.bot.get_channel(alert_channel_id)
                if alert_channel is not None:
                    try:
                        live_alert = await alert_channel.send(alert_info.get("custom_message", message)+role_mention, embed=embed)
                        live_alerts.append(
                            {"channel": live_alert.channel.id, "message": live_alert.id})
                    except disnake.Forbidden:
                        pass
                    except disnake.HTTPException:
                        pass
            elif not reuse_done:
                self.bot.log.debug(
                    f"Running alert reuse for {item.user.display_name}")
                if channel_cache.get("reusable_alerts", None) is not None:
                    for alert in channel_cache.reusable_alerts:
                        alert_channel_id = alert.get("channel", None)
                        alert_channel = self.bot.get_channel(alert_channel_id)
                        if alert_channel is not None:
                            if callback.alert_roles[str(alert_channel.guild.id)].get("title_match_phrase", None):
                                if callback.alert_roles[str(alert_channel.guild.id)].title_match_phrase not in item.title.lower():
                                    self.bot.log.info(
                                        f"{'[Youtube]' if isinstance(item, YoutubeVideo) else '[Twitch]'} Didn't match title phrase for {guild.name}, skipping alert")
                                    continue
                            try:
                                alert_message = await alert_channel.fetch_message(alert.get("message"))
                            except disnake.NotFound:
                                pass
                            else:
                                try:
                                    user_escaped = item.user.display_name.replace(
                                        '_', '\_')
                                    live_alert = await alert_message.edit(content=alert_info.get("custom_message", message)+role_mention, embed=embed)
                                    live_alerts.append(
                                        {"channel": live_alert.channel.id, "message": live_alert.id})
                                except disnake.Forbidden:
                                    pass
                                except disnake.HTTPException:
                                    pass
                # Since reuse is all done in the first iteration, don't waste time doing it again
                reuse_done = True

            match alert_info.mode:
                case 0:  # Temporary live channel mode

                    # Create channel overrides
                    NewChannelOverrides = {self.bot.user: SelfOverride}
                    if alert_info.role_id != "everyone":
                        NewChannelOverrides[guild.default_role] = DefaultRole
                    if alert_info.role_id is not None and alert_info.role_id != "everyone":
                        NewChannelOverrides[role] = OverrideRole

                    # Create temporary channel and add channel id to channel cache
                    try:
                        channel = await guild.create_text_channel(f"🔴{item.user.display_name.lower()}", overwrites=NewChannelOverrides, position=0)
                        if channel:
                            user_escaped = item.user.display_name.replace(
                                '_', '\_')
                            await channel.send(f"{user_escaped} is live! {link}")
                            live_channels.append(channel.id)
                    except disnake.Forbidden:
                        self.bot.log.warning(
                            f"Error creating text channels for {item.user.display_name} in guild {guild.name}")

                # Notification is already sent, nothing needed to be done
                case 1:
                    pass

                # Permanent channel. Do the same as above, but modify the existing channel, instead of making a new one
                case 2:
                    channel = self.bot.get_channel(alert_info["channel_id"])
                    if channel is not None:
                        try:
                            await channel.edit(name="🔴now-live")
                            live_channels.append(channel.id)
                        except disnake.Forbidden:
                            self.bot.log.warning(
                                f"Error updating channels for {item.user.display_name} in guild {channel.guild.name}")
                    else:
                        self.bot.log.warning(
                            f"Persistent channel not found for {item.user.display_name}")
            triggered_guilds.append(guild_id)

        if item.type != YoutubeVideoType.premiere:
            try:
                async with aiofiles.open("config/callbacks.yml") as c:
                    callback_yaml = load(await c.read(), Loader=Loader)

                if webhooks_info := callback_yaml.get("callbacks", {}).get(item.user.id):
                    for webhook in webhooks_info["webhooks"]:
                        if webhooks_info.get("title_match_phrase", None):
                            if webhooks_info["title_match_phrase"] not in item.title.lower():
                                self.bot.log.info(
                                    f"{'[Youtube]' if isinstance(item, YoutubeVideo) else '[Twitch]'} Title phrase for slack webhook {item.user.display_name} didn't match, skipping alert")
                                continue
                        if webhook not in channel_cache.get("triggered_guilds", []):
                                if webhook.startswith("https://hooks.slack.com"):
                                    if isinstance(item, YoutubeVideo):
                                        message = f"{item.user.display_name} is live on Youtube!\n{item.title}\nhttps://youtube.com/watch?v={item.id}"
                                    else:
                                        message = f"{item.user.display_name} is live on Twitch!\n{item.title}\nhttps://twitch.tv/{item.user.username}"
                                    try:
                                        r = await self.bot.aSession.post(webhook, json={"text": message}, headers={"Content-type": "application/json"})
                                        rb = (await r.read()).decode()
                                        if r.status == 200 and rb == 'ok':
                                            self.bot.log.info(f"{'[Youtube]' if isinstance(item, YoutubeVideo) else '[Twitch]'} Sent slack online webhook for {item.user.display_name}")
                                            triggered_guilds.append(webhook)
                                        else:
                                            self.bot.log.error(f"{'[Youtube]' if isinstance(item, YoutubeVideo) else '[Twitch]'} Error sending slack online webhook for {item.user.display_name}: {rb}")
                                    except client_exceptions.ClientError as e:
                                        self.bot.log.error(f"{'[Youtube]' if isinstance(item, YoutubeVideo) else '[Twitch]'} Error sending slack online webhook for {item.user.display_name}: {str(e)}")
                                elif webhook.startswith("https://discord.com/api/webhooks"):
                                    user_escaped = item.user.display_name.replace('_', '\_')
                                    if isinstance(item, YoutubeVideo):
                                        message = f"{user_escaped} is live on Youtube!\n{item.title}\nhttps://youtube.com/watch?v={item.id}"
                                    else:
                                        message = f"{user_escaped} is live on Twitch!\n{item.title}\nhttps://twitch.tv/{item.user.username}"
                                    hook = disnake.Webhook.from_url(webhook, session=self.bot.aSession)
                                    try:
                                        await hook.send(message)
                                        triggered_guilds.append(webhook)
                                    except (disnake.errors.NotFound, disnake.errors.Forbidden, disnake.errors.HTTPException) as e:
                                        self.bot.log.error(f"{'[Youtube]' if isinstance(item, YoutubeVideo) else '[Twitch]'} Error sending discord online webhook for {item.user.display_name}: {str(e)}")
                                    else:
                                        self.bot.log.info(f"{'[Youtube]' if isinstance(item, YoutubeVideo) else '[Twitch]'} Sent discord online webhook for {item.user.display_name}")

            except FileNotFoundError:
                pass
            except YAMLError:
                self.bot.log.error(
                    "Error parsing config/callbacks.yml, ignoring.")

        return live_channels, live_alerts, triggered_guilds

    async def update_youtube_title(self, video: YoutubeVideo, channel_cache: YoutubeChannelCache):
        if video.id == channel_cache.video_id:
            title_cache = await self.bot.db.get_yt_title_cache(video.channel)
            # Only the title can be updated in an embed.
            if title_cache.title != video.title:
                title_cache.title = video.title
                await self.bot.db.write_yt_title_cache(video.channel, title_cache)
                await self.bot.ratelimit_request(video.user)
                video.user = await self.bot.yapi.get_user(video.user)
                embed = self.get_stream_embed(video)
                await self.update_alert_messages(channel_cache, embed)

    async def update_alert_messages(self, channel_cache: Union[ChannelCache, YoutubeChannelCache], embed: disnake.Embed):
        for m in channel_cache.get("live_alerts", []):
            if channel := self.bot.get_channel(m.get("channel", None)):
                try:
                    message = await channel.fetch_message(m.get("message", None))
                    await message.edit(embed=embed)
                except disnake.NotFound:
                    pass
                except disnake.Forbidden:
                    pass

    def get_overwrites(self) -> tuple[disnake.PermissionOverwrite, disnake.PermissionOverwrite, disnake.PermissionOverwrite]:
        # Permission overrides
        # Make sure the bot has permission to access the channel
        SelfOverride = disnake.PermissionOverwrite()
        SelfOverride.view_channel = True
        SelfOverride.send_messages = True
        DefaultRole = disnake.PermissionOverwrite()  # Deny @everyone access
        DefaultRole.view_channel = False
        DefaultRole.send_messages = False
        # Give users with the role access to view only
        OverrideRole = disnake.PermissionOverwrite()
        OverrideRole.view_channel = True
        return SelfOverride, DefaultRole, OverrideRole

    def is_catchup(self, user: Union[User, YoutubeUser]) -> str:
        return ' [Catchup]' if user.origin == AlertOrigin.catchup else ''

    async def set_channels_offline(self, callback: Union[Callback, YoutubeCallback], channel_cache: Union[ChannelCache, YoutubeChannelCache]):
        """Iterate through all live channels, if applicable, either deleting them or renaming them to stream-offline depending on mode"""
        for channel_id in channel_cache.get("live_channels", []):
            if channel := self.bot.get_channel(channel_id):
                try:
                    match callback.alert_roles[str(channel.guild.id)].mode:
                        case 0:
                            await channel.delete()
                        case 2:
                            await channel.edit(name="stream-offline")
                except disnake.Forbidden:
                    continue
                except disnake.HTTPException:
                    continue

    async def set_twitch_alerts_offline(self, streamer: User, callback: Callback, channel_cache: ChannelCache):
        """Just like channels, iterate through the sent live alerts, and make them past tense."""
        # Find a vod to make the embed link to
        vod = None
        if stream_id := channel_cache.get("stream_id", None):
            vod = await self.bot.tapi.get_video_from_stream_id(streamer, stream_id)

        for alert_ids in channel_cache.get("live_alerts", []):
            if channel := self.bot.get_channel(alert_ids["channel"]):
                try:  # Try to get the live alerts message, skipping if not found
                    message = await channel.fetch_message(alert_ids["message"])
                except disnake.NotFound:
                    continue
                # Get the live alert embed, skipping it was removed, or something else happened
                if len(message.embeds) < 1:
                    continue
                embed = message.embeds[0]
                # Replace the applicable strings with past tense phrasing
                embed.set_author(name=f"{streamer.display_name} is now offline",
                                 url=embed.author.url, icon_url=embed.author.icon_url)
                embed.url = vod.url if vod else embed.url
                # embed.set_author(name=embed.author.name.replace("is now live on Twitch!", "was live on Twitch!"), url=embed.author.url)
                split_description = embed.description.split('Streaming ', 1)
                if len(split_description) > 1:
                    extracted_game = split_description[1].split('\n')[0]
                    if vod:  # Embed timestamp is the stream start time. Could also use vod.created_at, but meh
                        end_time = embed.timestamp + \
                            timedelta(seconds=vod.duration)
                    else:
                        end_time = utcnow()

                    # List the last 5 games played in the embed
                    if games := channel_cache.get("games", None):
                        if len(games) == 1:
                            past_games = f"Was streaming {extracted_game} for {human_timedelta(end_time, source=embed.timestamp, accuracy=2)}"
                        else:
                            sliced_games = {key: games[key]
                                            for key in list(games.keys())[:5]}
                            sliced_games[list(
                                sliced_games.keys())[-1]] += int(time()) - channel_cache.last_update
                            past_games_list = []
                            for game_name, length in sliced_games.items():
                                if length == 0:
                                    continue
                                past_games_list.append(
                                    f"{game_name} for ~{human_timedelta(embed.timestamp+timedelta(seconds=length), source=embed.timestamp, accuracy=2)}")
                            extra = " (5 most recent)" if len(
                                games) > 5 else ""
                            past_games = f"Was streaming{extra}:" + \
                                "\n" + ',\n'.join(past_games_list)
                    else:
                        # Fallback
                        self.bot.log.warning(
                            "Using fallback game extraction")
                        past_games = f"Was streaming {extracted_game} for ~{human_timedelta(end_time, source=embed.timestamp, accuracy=2)}"
                    if callback.alert_roles.get(str(channel.guild.id), {}).get("show_cest_time", False):
                        cest_tz = tz.gettz("CET")
                        start_time_cest = embed.timestamp.astimezone(
                            cest_tz).strftime("%H:%M")
                        end_time_cest = end_time.astimezone(
                            cest_tz).strftime("%H:%M %Z")
                        detailed_length = f"\n{start_time_cest} - {end_time_cest}"
                    else:
                        detailed_length = ""
                    embed.description = f"{past_games}{detailed_length}"
                    try:
                        await message.edit(content=f"{streamer.display_name} is now offline", embed=embed)
                    except disnake.Forbidden:
                        continue

        try:
            async with aiofiles.open("config/callbacks.yml") as c:
                callback_yaml = load(await c.read(), Loader=Loader)

            if webhooks_info := callback_yaml.get("callbacks", {}).get(streamer.id):

                for webhook in webhooks_info["webhooks"]:
                    if webhook in channel_cache["triggered_guilds"]:
                        if webhook.startswith("https://hooks.slack.com"):
                            message = f"{streamer.display_name} is no longer live on Twitch"
                            if vod:
                                message += "\n"
                                message += f"{vod.url}"
                            try:
                                r = await self.bot.aSession.post(webhook, json={"text": message}, headers={"Content-type": "application/json"})
                                rb = (await r.read()).decode()
                                if r.status == 200 and rb == 'ok':
                                    self.bot.log.info(f"[Twitch] Sent slack online webhook for {streamer.display_name}")
                                else:
                                    self.bot.log.error(f"[Twitch] Error sending slack online webhook for {streamer.display_name}: {rb}")
                            except client_exceptions.ClientError as e:
                                self.bot.log.error(f"[Twitch] Error sending slack online webhook for {streamer.display_name}: {str(e)}")
                        elif webhook.startswith("https://discord.com/api/webhooks"):
                            user_escaped = streamer.display_name.replace('_', '\_')
                            message = f"{user_escaped} is no longer live on Twitch"
                            if vod:
                                message += "\n"
                                message += f"{vod.url}"
                            hook = disnake.Webhook.from_url(webhook, session=self.bot.aSession)
                            try:
                                await hook.send(message)
                            except (disnake.errors.NotFound, disnake.errors.Forbidden, disnake.errors.HTTPException) as e:
                                self.bot.log.error(f"[Twitch] Error sending discord offline webhook for {streamer.display_name}: {str(e)}")
                            else:
                                self.bot.log.info(f"[Twitch] Sent discord offline webhook for {streamer.display_name}")

        except FileNotFoundError:
            pass
        except YAMLError:
            self.bot.log.error("Error parsing config/callbacks.yml, ignoring.")

    async def set_youtube_alerts_offline(self, channel: YoutubeUser, callback: Callback, channel_cache: YoutubeChannelCache):
        """Just like channels, iterate through the sent live alerts, and make them past tense."""
        for alert_ids in channel_cache.get("live_alerts", []):
            if c := self.bot.get_channel(alert_ids["channel"]):
                try:  # Try to get the live alerts message, skipping if not found
                    message = await c.fetch_message(alert_ids["message"])
                except disnake.NotFound:
                    continue
                # Get the live alert embed, skipping it was removed, or something else happened
                if len(message.embeds) < 1:
                    continue
                embed = message.embeds[0]
                # Replace the applicable strings with past tense phrasing
                embed.set_author(name=f"{channel.display_name} is now offline",
                                 url=embed.author.url, icon_url=embed.author.icon_url)
                video_end_time = await self.bot.yapi.has_video_ended(channel_cache.video_id)
                end_time = parser.parse(video_end_time) if video_end_time else utcnow()
                if callback["alert_roles"].get(str(c.guild.id), {}).get("show_cest_time", False):
                    cest_tz = tz.gettz("CET")
                    start_time_cest = embed.timestamp.astimezone(
                        cest_tz).strftime("%H:%M")
                    end_time_cest = end_time.astimezone(
                        cest_tz).strftime("%H:%M %Z")
                    detailed_length = f"\n{start_time_cest} - {end_time_cest}"
                else:
                    detailed_length = ""
                embed.description = f"Was streaming for {'~' if not video_end_time else ''}{human_timedelta(end_time, source=embed.timestamp, accuracy=2)}{detailed_length}"
                try:
                    await message.edit(content=f"{channel.display_name} is now offline", embed=embed)
                except disnake.Forbidden:  # In case something weird happens
                    continue

        try:
            async with aiofiles.open("config/callbacks.yml") as c:
                callback_yaml = load(await c.read(), Loader=Loader)

            if webhooks_info := callback_yaml.get("callbacks", {}).get(channel.id):
                for webhook in webhooks_info["webhooks"]:
                    if webhook in channel_cache["triggered_guilds"]:
                        if webhook.startswith("https://hooks.slack.com"):
                            message = f"{channel.display_name} is no longer live on Youtube\nhttps://youtube.com/watch?v={channel_cache.video_id}"
                            try:
                                r = await self.bot.aSession.post(webhook, json={"text": message}, headers={"Content-type": "application/json"})
                                rb = (await r.read()).decode()
                                if r.status == 200 and rb == 'ok':
                                    self.bot.log.info(f"[Youtube] Sent slack online webhook for {channel.display_name}")
                                else:
                                    self.bot.log.error(f"[Youtube] Error sending slack online webhook for {channel.display_name}: {rb}")
                            except client_exceptions.ClientError as e:
                                self.bot.log.error(f"[Youtube] Error sending slack online webhook for {channel.display_name}: {str(e)}")
                        elif webhook.startswith("https://discord.com/api/webhooks"):
                            user_escaped = channel.display_name.replace('_', '\_')
                            message = f"{user_escaped} is no longer live on Youtube\nhttps://youtube.com/watch?v={channel_cache.video_id}"
                            hook = disnake.Webhook.from_url(webhook, session=self.bot.aSession)
                            try:
                                await hook.send(message)
                            except (disnake.errors.NotFound, disnake.errors.Forbidden, disnake.errors.HTTPException) as e:
                                self.bot.log.error(f"[Youtube] Error sending discord offline webhook for {channel.display_name}: {str(e)}")
                            else:
                                self.bot.log.info(f"[Youtube] Sent discord offline webhook for {channel.display_name}")

        except FileNotFoundError:
            pass
        except YAMLError:
            self.bot.log.error("Error parsing config/callbacks.yml, ignoring.")

    def get_stream_embed(self, item: Union[Stream, YoutubeVideo], **kwargs) -> disnake.Embed:
        if isinstance(item, Stream):
            embed = disnake.Embed(
                title=item.title, url=f"https://twitch.tv/{item.user.name}",
                description=f"Streaming {item.game}\n[Watch Stream](https://twitch.tv/{item.user.name})",
                colour=TWITCH_PURPLE, timestamp=item.started_at)
            embed.set_author(name=f"{item.user.display_name} is now live on Twitch!",
                             url=f"https://twitch.tv/{item.user.name}", icon_url=item.user.avatar)

        elif isinstance(item, TitleEvent):
            embed = disnake.Embed(
                title=item.title, url=f"https://twitch.tv/{item.broadcaster.username}",
                description=f"Streaming {item.game}\n[Watch Stream](https://twitch.tv/{item.broadcaster.name})",
                colour=TWITCH_PURPLE, timestamp=kwargs["stream"].started_at)
            embed.set_author(name=f"{item.broadcaster.display_name} is now live on Twitch!",
                             url=f"https://twitch.tv/{item.broadcaster.username}", icon_url=kwargs["stream"].user.avatar)

        elif isinstance(item, YoutubeVideo):
            embed = disnake.Embed(
                title=item.title, url=f"https://youtube.com/watch?v={item.id}",
                description=f"[Watch Stream](https://youtube.com/watch?v={item.id})",
                colour=YOUTUBE_RED, timestamp=item.started_at)
            embed.set_author(name=f"{item.user.display_name} is now live on Youtube!",
                             url=f"https://youtube.com/watch?v={item.id}", icon_url=item.user.avatar_url)

        embed.set_footer(text=self.footer_msg)
        return embed

    async def title_change_update_alerts(self, event: TitleEvent, stream: Stream, old_game: str):
        await self.bot.ratelimit_request(event.broadcaster)
        # channel_cache = await get_channel_cache()
        channel_cache = await self.bot.db.get_channel_cache(stream.user)
        stream.user = await self.bot.tapi.get_user(user=stream.user)
        embed = self.get_stream_embed(event, stream=stream)
        await self.update_alert_messages(channel_cache, embed)

        # Add new game to games list if applicable
        if channel_cache.get("games", None) and event.game != old_game:
            old_time = channel_cache.games.get(event.game_name, 0)
            if event.game_name in channel_cache.games.keys():
                channel_cache.games.pop(event.game_name, None)
            if channel_cache.games.get(old_game, None) != None:
                channel_cache.games[old_game] = (
                    int(time()) - channel_cache.last_update) + old_time
            channel_cache.games[event.game_name] = old_time
            channel_cache.last_update = int(time())
            await self.bot.db.write_channel_cache(stream.user, channel_cache)

    async def viewer_count_milestones(self, stream: Stream, callback: Callback, channel_cache: ChannelCache):
        # Check if view count is higher than minimum and if it exceeds a previous announcement + interval amount
        if stream.view_count >= self.bot.viewer_milestones_minimum and stream.view_count >= channel_cache.get("viewer_milestone", 0)+self.bot.viewer_milestones_interval:
            self.bot.log.info(
                f"{stream.user.username} => VIEW COUNT ({stream.view_count:,}) (Twitch)")
            # Do some funky maths to calculate the interval that it passed
            channel_cache.viewer_milestone = floor((stream.view_count-self.bot.viewer_milestones_minimum) /
                                                   self.bot.viewer_milestones_interval)*self.bot.viewer_milestones_interval+self.bot.viewer_milestones_minimum
            await self.bot.db.write_channel_cache(stream.user, channel_cache)

            # Create embed message
            stream.user = await self.bot.tapi.get_user(user=stream.user)
            view_embed = disnake.Embed(
                title=f"{stream.user.display_name} just passed {channel_cache.get('viewer_milestone', 0):,} viewers!", url=f"https://twitch.tv/{stream.user.name}",
                description=f"Streaming {stream.game} for {human_timedelta(stream.started_at, suffix=False, accuracy=2)}\n[Watch Stream](https://twitch.tv/{stream.user.name})",
                colour=TWITCH_PURPLE, timestamp=utcnow())
            view_embed.set_author(
                name=stream.title, url=f"https://twitch.tv/{stream.user.name}", icon_url=stream.user.avatar)
            # This got stuck when combined. Not sure why
            view_embed.set_footer(text=self.footer_msg)

            for guild_id, alert_info in callback.alert_roles.items():
                guild = self.bot.get_guild(int(guild_id))
                if guild is None:
                    continue

                if alert_info.get("title_match_phrase", None):
                    if alert_info.title_match_phrase not in stream.title.lower():
                        self.bot.log.info(
                            f"[Twitch] {stream.user.display_name} title phrase for {guild.name} didn't match, skipping alert")
                        continue

                # Format role mention
                if alert_info.role_id == "everyone":
                    role_mention = f" {guild.default_role}"
                elif alert_info.role_id == None:
                    role_mention = ""
                else:
                    role = guild.get_role(alert_info.role_id)
                    role_mention = f" {getattr(role, 'mention', '')}"

                if alert_channel := self.bot.get_channel(alert_info.get("notif_channel_id", None)):
                    try:
                        # live_alert = await alert_channel.send(f"{stream.user.display_name} is live on Twitch!{role_mention}", embed=embed)
                        user_escaped = stream.user.display_name.replace(
                            '_', '\_')
                        await alert_channel.send(f"{user_escaped} just passed {channel_cache.get('viewer_milestone', 0):,} viewers!{role_mention}", embed=view_embed)
                    except disnake.Forbidden:
                        pass
                    except disnake.HTTPException:
                        pass


def setup(bot):
    bot.add_cog(StreamStateManager(bot))
