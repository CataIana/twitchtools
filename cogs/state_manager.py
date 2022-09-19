from datetime import timedelta
from time import time
from typing import TYPE_CHECKING, Union

import disnake
from dateutil import parser
from disnake.ext import commands
from disnake.utils import utcnow

from twitchtools import (AlertOrigin, PartialUser, PartialYoutubeUser, Stream,
                         TitleEvent, User, YoutubeUser, YoutubeVideo,
                         human_timedelta)
from twitchtools.enums import ChannelCache, YoutubeChannelCache
from twitchtools.user import PartialYoutubeUser, YoutubeUser

if TYPE_CHECKING:
    from main import TwitchCallBackBot


class StreamStateManager(commands.Cog):
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()
        self.ignore_cooldowns: bool = False  # Used for debugging/development
        self.twitch_purple = 9520895  # Hex #9146FF
        self.youtube_red = 16711680  # Hex FF0000

    async def on_title_change(self, event: TitleEvent):
        await self.bot.wait_until_ready()
        title_callback = await self.bot.db.get_title_callback(event.broadcaster)
        await self.bot.wait_until_db_ready()
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

        stream = await self.bot.tapi.get_stream(event.broadcaster.username, origin=AlertOrigin.callback)
        if stream:
            await self.bot.ratelimit_request(event.broadcaster)
            # channel_cache = await get_channel_cache()
            channel_cache = await self.bot.db.get_channel_cache(stream.user)
            stream.user = await self.bot.tapi.get_user(user=stream.user)
            embed = disnake.Embed(
                title=event.title, url=f"https://twitch.tv/{event.broadcaster.username}",
                description=f"Streaming {event.game}\n[Watch Stream](https://twitch.tv/{event.broadcaster.name})",
                colour=self.twitch_purple, timestamp=stream.started_at)
            embed.set_author(name=f"{event.broadcaster.display_name} is now live on Twitch!",
                             url=f"https://twitch.tv/{event.broadcaster.username}", icon_url=stream.user.avatar)
            embed.set_footer(text="Mew")
            # Add new game to games list if applicable
            if "games" in channel_cache.keys() and event.game != old_game:
                old_time = channel_cache.games.get(event.game_name, 0)
                if event.game_name in channel_cache.games.keys():
                    channel_cache.games.pop(event.game_name, None)
                if channel_cache.games.get(old_game, None) != None:
                    channel_cache.games[old_game] = (
                        int(time()) - channel_cache.last_update) + old_time
                channel_cache.games[event.game_name] = old_time
                channel_cache.last_update = int(time())
                # await write_channel_cache(channel_cache)
                await self.bot.db.write_channel_cache(stream.user, channel_cache)
            for m in channel_cache.get("live_alerts", []):
                channel = self.bot.get_channel(m.get("channel", None))
                if channel:
                    try:
                        message = await channel.fetch_message(m.get("message", None))
                        await message.edit(embed=embed)
                    except disnake.NotFound:
                        pass
                    except disnake.Forbidden:
                        pass
            return

        if title_callback is None:
            return

        user = await self.bot.tapi.get_user(user_id=event.broadcaster.id)
        # Create embed for discord
        embed = disnake.Embed(
            url=f"https://twitch.tv/{event.broadcaster.username}", colour=self.twitch_purple, timestamp=utcnow())
        if event.title != old_title:
            embed.add_field(name="Old Title", value=old_title, inline=True)
            embed.add_field(name="New Title", value=event.title, inline=True)
        if event.game != old_game:
            embed.add_field(name="Old Game", value=old_game, inline=True)
            embed.add_field(name="New Game", value=event.game, inline=True)
        embed.set_author(name=f"{event.broadcaster.display_name} updated their {' and '.join(updated)}!",
                         url=f"https://twitch.tv/{event.broadcaster.username}", icon_url=user.avatar)
        embed.set_footer(text="Mew")

        self.bot.log.info(f"{event.broadcaster.username} => TITLE UPDATE")

        # Send embed to each defined channel
        for data in title_callback["alert_roles"].values():
            c = self.bot.get_channel(data["notif_channel_id"])
            if c is not None:
                if data['role_id'] is None:
                    role_mention = ""
                elif data["role_id"] == "everyone":
                    role_mention = "@everyone"
                else:
                    role_mention = f"<@&{data['role_id']}>"
                try:
                    await c.send(f"{role_mention}", embed=embed)
                except disnake.Forbidden:
                    pass
                except disnake.HTTPException:
                    pass

    async def on_streamer_offline(self, streamer: Union[User, PartialUser]):
        await self.bot.wait_until_ready()
        await self.bot.wait_until_db_ready()
        # channel_cache = await get_channel_cache()
        channel_cache = await self.bot.db.get_channel_cache(streamer)
        callback = await self.bot.db.get_callback(streamer)
        if callback is None:
            return
        # Check if there's anything to even be done, if not, just silently ignore
        # if channel_cache.get("live_channels", None) is None and channel_cache.get("live_alerts", None) is None:
        #     return
        if not self.is_live(channel_cache):
            return
        self.bot.log.info(f"{streamer} => OFFLINE (Twitch)")
        # Iterate through all live channels, if applicable, either deleting them or renaming them to stream-offline depending on mode
        for channel_id in channel_cache.get("live_channels", []):
            channel = self.bot.get_channel(channel_id)
            if channel is not None:
                try:
                    if callback["alert_roles"][str(channel.guild.id)]["mode"] == 0:
                        await channel.delete()
                    elif callback["alert_roles"][str(channel.guild.id)]["mode"] == 2:
                        await channel.edit(name="stream-offline")
                except disnake.Forbidden:
                    continue
                except disnake.HTTPException:
                    continue

        # Delete live channel data after being used
        channel_cache.pop("live_channels", None)

        vod = None
        if channel_cache.get("stream_id", None):
            vod = await self.bot.tapi.get_video_from_stream_id(streamer, channel_cache.stream_id)
        # Just like channels, iterate through the sent live alerts, and make them past tense. 100% suseptible to edge cases
        for alert_ids in channel_cache.get("live_alerts", []):
            channel = self.bot.get_channel(alert_ids["channel"])
            if channel is not None:
                try:  # Try to get the live alerts message, skipping if not found
                    message = await channel.fetch_message(alert_ids["message"])
                except disnake.NotFound:
                    continue
                else:
                    try:  # Get the live alert embed, skipping it was removed, or something else happened
                        embed = message.embeds[0]
                    except IndexError:
                        continue
                    else:
                        try:  # Replace the applicable strings with past tense phrasing
                            embed.set_author(
                                name=f"{streamer.display_name} is now offline", url=embed.author.url, icon_url=embed.author.icon_url)
                            if vod:
                                embed.url = vod.url
                            #embed.set_author(name=embed.author.name.replace("is now live on Twitch!", "was live on Twitch!"), url=embed.author.url)
                            split_description = embed.description.split(
                                'Streaming ', 1)
                            if len(split_description) > 1:
                                extracted_game = split_description[1].split('\n')[
                                    0]
                                if vod:  # Embed timestamp is the stream start time. Could also use vod.created_at, but meh
                                    end_time = embed.timestamp + \
                                        timedelta(seconds=vod.duration)
                                else:
                                    end_time = utcnow()
                                if "games" in channel_cache.keys():
                                    games = channel_cache.games  # Limit to last 5 games
                                    if len(games) == 1:
                                        past_games = f"Was streaming {extracted_game} for {human_timedelta(end_time, source=embed.timestamp, accuracy=2)}"
                                    else:
                                        sliced_games = {key: games[key] for key in list(games.keys())[
                                            :5]}
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
                                embed.description = past_games
                                try:
                                    await message.edit(content=f"{streamer.display_name} is now offline", embed=embed)
                                except disnake.Forbidden:  # In case something weird happens
                                    continue
                        except IndexError:  # In case something weird happens when parsing the embed values
                            self.bot.log.warning(
                                f"Error editing message to offline for {streamer.display_name} in {channel.guild.name}")

        # Remove data once used
        if channel_cache.get("live_alerts", []) != []:
            channel_cache.reusable_alerts = channel_cache.live_alerts
        channel_cache.pop("live_alerts", None)
        channel_cache.pop("stream_id", None)
        channel_cache.is_live = False
        channel_cache.pop("games", None)
        channel_cache.pop("last_update", None)

        # Update cache
        # await write_channel_cache(channel_cache)
        await self.bot.db.write_channel_cache(streamer, channel_cache)

    async def on_youtube_streamer_offline(self, channel: Union[YoutubeUser, PartialYoutubeUser]):
        await self.bot.wait_until_ready()
        await self.bot.wait_until_db_ready()
        # Due to lack of an event, only catchup will trigger this

        channel_cache = await self.bot.db.get_yt_channel_cache(channel)
        callback = await self.bot.db.get_yt_callback(channel)
        if callback is None:
            return
        # Check if there's anything to even be done, if not, just silently ignore
        # if channel_cache.get("live_channels", None) is None and channel_cache.get("live_alerts", None) is None:
        #     return
        if not self.is_live(channel_cache):
            return
        self.bot.log.info(f"{channel.display_name} => OFFLINE (Youtube)")
        # Iterate through all live channels, if applicable, either deleting them or renaming them to stream-offline depending on mode
        for channel_id in channel_cache.get("live_channels", []):
            c = self.bot.get_channel(channel_id)
            if c is not None:
                try:
                    if callback["alert_roles"][str(c.guild.id)]["mode"] == 0:
                        await c.delete()
                    elif callback["alert_roles"][str(c.guild.id)]["mode"] == 2:
                        await c.edit(name="stream-offline")
                except disnake.Forbidden:
                    continue
                except disnake.HTTPException:
                    continue

        # Delete live channel data after being used
        channel_cache.pop("live_channels", None)

        # Just like channels, iterate through the sent live alerts, and make them past tense. 100% suseptible to edge cases
        for alert_ids in channel_cache.get("live_alerts", []):
            c = self.bot.get_channel(alert_ids["channel"])
            if c is not None:
                try:  # Try to get the live alerts message, skipping if not found
                    message = await c.fetch_message(alert_ids["message"])
                except disnake.NotFound:
                    continue
                else:
                    try:  # Get the live alert embed, skipping it was removed, or something else happened
                        embed = message.embeds[0]
                    except IndexError:
                        continue
                    else:
                        try:  # Replace the applicable strings with past tense phrasing
                            embed.set_author(
                                name=f"{channel.display_name} is now offline", url=embed.author.url, icon_url=embed.author.icon_url)
                            video_end_time = await self.bot.yapi.has_video_ended(channel_cache.video_id)
                            if video_end_time:
                                end_time = parser.parse(video_end_time)
                            else:
                                end_time = utcnow()
                            embed.description = f"Was streaming for ~{human_timedelta(end_time, source=embed.timestamp, accuracy=2)}"
                            try:
                                await message.edit(content=f"{channel.display_name} is now offline", embed=embed)
                            except disnake.Forbidden:  # In case something weird happens
                                continue
                        except IndexError:  # In case something weird happens when parsing the embed values
                            self.bot.log.warning(
                                f"Error editing message to offline for {channel.display_name} in {c.guild.name}")

        # Remove data once used
        if channel_cache.get("live_alerts", []) != []:
            channel_cache.reusable_alerts = channel_cache.live_alerts
        channel_cache.pop("live_alerts", None)
        channel_cache.pop("video_id", None)
        channel_cache.is_live = False
        channel_cache.pop("last_update", None)

        # Update cache
        # await write_channel_cache(channel_cache)
        await self.bot.db.write_yt_channel_cache(channel, channel_cache)

    def on_cooldown(self, alert_cooldown: int) -> bool:
        if int(time()) - alert_cooldown < 600 and not self.ignore_cooldowns:
            return True
        return False

    def is_live(self, channel_cache: Union[ChannelCache, YoutubeChannelCache]):
        # To reduce the likelyhood of strange errors, clarify this.
        if channel_cache.get("is_live", False):
            return True

    async def on_streamer_online(self, stream: Stream):
        await self.bot.wait_until_ready()
        await self.bot.wait_until_db_ready()

        channel_cache = await self.bot.db.get_channel_cache(stream.user)
        callback = await self.bot.db.get_callback(stream.user)
        on_cooldown = self.on_cooldown(channel_cache.get("alert_cooldown", 0))

        # Do not re-run this function is the streamer is already live
        if self.is_live(channel_cache):
            if stream.origin == AlertOrigin.callback:
                self.bot.log.info(f"Received alert while already live for {stream.user.username}, ignoring")
            return

        if on_cooldown:  # There is a 10 minute cooldown between alerts, but live channels will still be created
            self.bot.log.info(
                f"Notification cooldown active for {stream.user.username}, restoring old channels/messages")

        self.bot.log.info(f"{stream.user.username} => ONLINE (Twitch)")

        if callback["display_name"] != stream.user.display_name:
            callback["display_name"] = stream.user.display_name
            await self.bot.db.write_callback(stream.user, callback)

        # Create embed message
        stream.user = await self.bot.tapi.get_user(user=stream.user)
        embed = disnake.Embed(
            title=stream.title, url=f"https://twitch.tv/{stream.user.name}",
            description=f"Streaming {stream.game}\n[Watch Stream](https://twitch.tv/{stream.user.name})",
            colour=self.twitch_purple, timestamp=stream.started_at)
        embed.set_author(name=f"{stream.user.display_name} is now live on Twitch!",
                         url=f"https://twitch.tv/{stream.user.name}", icon_url=stream.user.avatar)
        embed.set_footer(text="Mew")

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

        live_channels = []
        live_alerts = []
        reuse_done = False
        for guild_id, alert_info in callback["alert_roles"].items():
            guild = self.bot.get_guild(int(guild_id))
            if guild is None:
                continue

            # Format role mention
            if alert_info["role_id"] == "everyone":
                role_mention = f" {guild.default_role}"
            elif alert_info["role_id"] == None:
                role_mention = ""
            else:
                role = guild.get_role(alert_info["role_id"])
                role_mention = f" {role.mention}"

            if not on_cooldown:  # Send live alert if not on alert cooldown, and append channel id and message id to channel cache
                alert_channel_id = alert_info.get("notif_channel_id", None)
                alert_channel = self.bot.get_channel(alert_channel_id)
                if alert_channel is not None:
                    try:
                        user_escaped = stream.user.display_name.replace(
                            '_', '\_')
                        live_alert = await alert_channel.send(alert_info.get("custom_message", f"{user_escaped} is live on Twitch!")+role_mention, embed=embed)
                        live_alerts.append(
                            {"channel": live_alert.channel.id, "message": live_alert.id})
                    except disnake.Forbidden:
                        pass
                    except disnake.HTTPException:
                        pass
            elif not reuse_done:
                self.bot.log.debug(f"Running alert reuse for {stream.user.display_name}")
                if channel_cache.get("reusable_alerts", None) is not None:
                    for alert in channel_cache.reusable_alerts:
                        alert_channel_id = alert.get("channel", None)
                        alert_channel = self.bot.get_channel(alert_channel_id)
                        if alert_channel is not None:
                            try:
                                alert_message = await alert_channel.fetch_message(alert.get("message"))
                            except disnake.NotFound:
                                pass
                            else:
                                try:
                                    user_escaped = stream.user.display_name.replace(
                                        '_', '\_')
                                    live_alert = await alert_message.edit(content=alert_info.get("custom_message", f"{user_escaped} is live on Twitch!")+role_mention, embed=embed)
                                    live_alerts.append(
                                        {"channel": live_alert.channel.id, "message": live_alert.id})
                                except disnake.Forbidden:
                                    pass
                                except disnake.HTTPException:
                                    pass
                # Since reuse is all done in the first iteration, don't waste time doing it again
                reuse_done = True

            if alert_info["mode"] == 0:  # Temporary live channel mode

                # Create channel overrides
                NewChannelOverrides = {self.bot.user: SelfOverride}
                if alert_info["role_id"] != "everyone":
                    NewChannelOverrides[guild.default_role] = DefaultRole
                if alert_info["role_id"] is not None and alert_info["role_id"] != "everyone":
                    NewChannelOverrides[role] = OverrideRole

                # Check if channel doesn't already exist. Kind of a bad idea, but does effectively prevent duplicate channels
                # if f"🔴{stream.user.username}" not in [channel.name for channel in guild.text_channels]:
                    # Create temporary channel and add channel id to channel cache
                try:
                    channel = await guild.create_text_channel(f"🔴{stream.user.username}", overwrites=NewChannelOverrides, position=0)
                    if channel:
                        user_escaped = stream.user.display_name.replace(
                            '_', '\_')
                        await channel.send(f"{user_escaped} is live! https://twitch.tv/{stream.user.name}")
                        live_channels.append(channel.id)
                except disnake.Forbidden:
                    self.bot.log.warning(
                        f"Error creating text channels for {stream.user.username} in guild {guild.name}")

            # Notification is already sent, nothing needed to be done
            elif alert_info["mode"] == 1:
                pass

            # Permanent channel. Do the same as above, but modify the existing channel, instead of making a new one
            elif alert_info["mode"] == 2:
                channel = self.bot.get_channel(alert_info["channel_id"])
                if channel is not None:
                    try:
                        await channel.edit(name="🔴now-live")
                        live_channels.append(channel.id)
                    except disnake.Forbidden:
                        self.bot.log.warning(
                            f"Error updating channels for {stream.user.username} in guild {channel.guild.name}")
                else:
                    self.bot.log.warning(
                        f"Persistent channel not found for {stream.user.username}")

        # Finally, combine all data into channel cache, and update the file
        channel_cache = {
            "alert_cooldown": int(time()),
            "user_login": stream.user.username,
            "stream_id": stream.stream_id,
            "is_live": True,
            "live_channels": live_channels,
            "live_alerts": live_alerts,
            "last_update": int(time()),
            "games": {stream.game_name: 0}
        }

        # await write_channel_cache(channel_cache)
        await self.bot.db.write_channel_cache(stream.user, channel_cache)

    async def on_youtube_streamer_online(self, video: YoutubeVideo):
        await self.bot.wait_until_ready()
        await self.bot.wait_until_db_ready()
        # All videos that come through here are all live videos
        channel_cache = await self.bot.db.get_yt_channel_cache(video.channel)
        callback = await self.bot.db.get_yt_callback(video.channel)
        on_cooldown = self.on_cooldown(channel_cache.get("alert_cooldown", 0))

        # Do not re-run this function is the streamer is already live
        if self.is_live(channel_cache):
            if video.id == channel_cache.video_id:
                title_cache = await self.bot.db.get_yt_title_cache(video.channel)
                if title_cache.title != video.title:
                    title_cache.title = video.title
                    await self.bot.db.write_yt_title_cache(video.channel, title_cache)
                await self.bot.ratelimit_request(video.user)
                video.user = await self.bot.yapi.get_user(video.user)
                embed = disnake.Embed(
                    title=video.title, url=f"https://youtube.com/watch?v={video.id}",
                    description=f"[Watch Stream](https://youtube.com/watch?v={video.id})",
                    colour=self.youtube_red, timestamp=video.started_at)
                embed.set_author(name=f"{video.user.display_name} is now live on Youtube!",
                                    url=f"https://youtube.com/watch?v={video.id}", icon_url=video.user.avatar_url)
                embed.set_footer(text="Mew")
                # Add new game to games list if applicable
                for m in channel_cache.get("live_alerts", []):
                    channel = self.bot.get_channel(m.get("channel", None))
                    if channel:
                        try:
                            message = await channel.fetch_message(m.get("message", None))
                            await message.edit(embed=embed)
                        except disnake.NotFound:
                            pass
                        except disnake.Forbidden:
                            pass
            if video.origin == AlertOrigin.callback:
                self.bot.log.info(
                    f"Received alert while already live for {video.user.display_name}, ignoring")
            return

        if on_cooldown:  # There is a 10 minute cooldown between alerts, but live channels will still be created
            self.bot.log.info(
                f"Notification cooldown active for {video.user.display_name}, restoring old channels/messages")

        self.bot.log.info(
            f"{video.user.display_name} => ONLINE (Youtube)")

        if callback["display_name"] != video.user.display_name:
            callback["display_name"] = video.user.display_name
            await self.bot.db.write_yt_callback(video.user, callback)

        # Create embed message
        video.user = await self.bot.yapi.get_user(video.user)
        embed = disnake.Embed(
            title=video.title, url=f"https://youtube.com/watch?v={video.id}",
            description=f"[Watch Stream](https://youtube.com/watch?v={video.id})",
            colour=self.youtube_red, timestamp=video.started_at)
        embed.set_author(name=f"{video.user.display_name} is now live on Youtube!",
                         url=f"https://youtube.com/watch?v={video.id}", icon_url=video.user.avatar_url)
        embed.set_footer(text="Mew")

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

        live_channels = []
        live_alerts = []
        reuse_done = False
        for guild_id, alert_info in callback["alert_roles"].items():
            guild = self.bot.get_guild(int(guild_id))
            if guild is None:
                continue

            # Format role mention
            if alert_info["role_id"] == "everyone":
                role_mention = f" {guild.default_role}"
            elif alert_info["role_id"] == None:
                role_mention = ""
            else:
                role = guild.get_role(alert_info["role_id"])
                role_mention = f" {role.mention}"

            if not on_cooldown:  # Send live alert if not on alert cooldown, and append channel id and message id to channel cache
                alert_channel_id = alert_info.get("notif_channel_id", None)
                alert_channel = self.bot.get_channel(alert_channel_id)
                if alert_channel is not None:
                    try:
                        user_escaped = video.user.display_name.replace(
                            '_', '\_')
                        live_alert = await alert_channel.send(alert_info.get("custom_message", f"{user_escaped} is live on Youtube!")+role_mention, embed=embed)
                        live_alerts.append(
                            {"channel": live_alert.channel.id, "message": live_alert.id})
                    except disnake.Forbidden:
                        pass
                    except disnake.HTTPException:
                        pass
            elif not reuse_done:
                self.bot.log.debug(f"Running alert reuse for {video.user.display_name}")
                if channel_cache.get("reusable_alerts", None) is not None:
                    for alert in channel_cache.reusable_alerts:
                        alert_channel_id = alert.get("channel", None)
                        alert_channel = self.bot.get_channel(alert_channel_id)
                        if alert_channel is not None:
                            try:
                                alert_message = await alert_channel.fetch_message(alert.get("message"))
                            except disnake.NotFound:
                                pass
                            else:
                                try:
                                    user_escaped = video.user.display_name.replace(
                                        '_', '\_')
                                    live_alert = await alert_message.edit(content=alert_info.get("custom_message", f"{user_escaped} is live on Youtube!")+role_mention, embed=embed)
                                    live_alerts.append(
                                        {"channel": live_alert.channel.id, "message": live_alert.id})
                                except disnake.Forbidden:
                                    pass
                                except disnake.HTTPException:
                                    pass
                # Since reuse is all done in the first iteration, don't waste time doing it again
                reuse_done = True

            if alert_info["mode"] == 0:  # Temporary live channel mode

                # Create channel overrides
                NewChannelOverrides = {self.bot.user: SelfOverride}
                if alert_info["role_id"] != "everyone":
                    NewChannelOverrides[guild.default_role] = DefaultRole
                if alert_info["role_id"] is not None and alert_info["role_id"] != "everyone":
                    NewChannelOverrides[role] = OverrideRole

                # Check if channel doesn't already exist. Kind of a bad idea, but does effectively prevent duplicate channels
                # if f"🔴{stream.user.username}" not in [channel.name for channel in guild.text_channels]:
                    # Create temporary channel and add channel id to channel cache
                try:
                    channel = await guild.create_text_channel(f"🔴{video.user.display_name.lower()}", overwrites=NewChannelOverrides, position=0)
                    if channel:
                        user_escaped = video.user.display_name.replace(
                            '_', '\_')
                        await channel.send(f"{user_escaped} is live! https://youtube.com/watch?v={video.id}")
                        live_channels.append(channel.id)
                except disnake.Forbidden:
                    self.bot.log.warning(
                        f"Error creating text channels for {video.user.display_name} in guild {guild.name}")

            # Notification is already sent, nothing needed to be done
            elif alert_info["mode"] == 1:
                pass

            # Permanent channel. Do the same as above, but modify the existing channel, instead of making a new one
            elif alert_info["mode"] == 2:
                channel = self.bot.get_channel(alert_info["channel_id"])
                if channel is not None:
                    try:
                        await channel.edit(name="🔴now-live")
                        live_channels.append(channel.id)
                    except disnake.Forbidden:
                        self.bot.log.warning(
                            f"Error updating persistent channel {video.user.display_name} in guild {channel.guild.name}")
                else:
                    self.bot.log.warning(
                        f"Persistent channel not found for {video.user.display_name}")

        # Finally, combine all data into channel cache, and update the file
        channel_cache = {
            "alert_cooldown": int(time()),
            "channel_id": video.channel.id,
            "video_id": video.id,
            "is_live": True,
            "live_channels": live_channels,
            "live_alerts": live_alerts,
            "last_update": int(time())
        }

        # await write_channel_cache(channel_cache)
        await self.bot.db.write_yt_channel_cache(video.user, channel_cache)


def setup(bot):
    bot.add_cog(StreamStateManager(bot))
