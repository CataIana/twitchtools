from typing import TYPE_CHECKING, Optional

from disnake.ext import commands, tasks

from twitchtools import (AlertOrigin, ApplicationCustomContext, Callback,
                         PartialUser, PartialYoutubeUser, YoutubeCallback,
                         has_manage_permissions)
from twitchtools.exceptions import (VideoNotFound, VideoNotStream,
                                    VideoStreamEnded)

if TYPE_CHECKING:
    from twitchtools import TwitchCallBackBot


class Catchup(commands.Cog):
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()
        self.twitch_backup_checks.start()
        self.youtube_backup_checks.start()

    def cog_unload(self):
        self.twitch_backup_checks.cancel()
        self.youtube_backup_checks.cancel()

    @tasks.loop(seconds=1800)
    async def twitch_backup_checks(self):
        await self.twitch_catchup()
        self.bot.log.debug("Ran twitch catchup")

    # Youtube callbacks are extremely unreliable and need a higher frequency. Also stream ends are only triggered by catchup
    @tasks.loop(seconds=600)
    async def youtube_backup_checks(self):
        await self.youtube_catchup()
        self.bot.log.debug("Ran youtube catchup")

    @commands.slash_command()
    async def catchup(self, ctx: ApplicationCustomContext):
        pass

    @catchup.sub_command(name="all", description="Owner Only: Run streamer catchup manually")
    @commands.is_owner()
    @commands.cooldown(1, 10, commands.BucketType.default)
    async def catchup_all(self, ctx: ApplicationCustomContext):
        await ctx.response.defer(ephemeral=True)
        await self.twitch_catchup()
        await self.youtube_catchup()
        self.bot.log.info("Finished manual catchup")
        await ctx.send(f"{self.bot.emotes.success} Finished catchup!", ephemeral=True)
    
    @catchup.sub_command(name="server", description="Run streamer catchup manually for streamers in this server")
    @has_manage_permissions()
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def catchup_server(self, ctx: ApplicationCustomContext):
        await ctx.response.defer(ephemeral=True)
        twitch_filtered_callbacks = {s: c for s, c in (await self.bot.db.get_all_callbacks()).items() if str(ctx.guild.id) in c.alert_roles.keys()}
        await self.twitch_catchup(twitch_filtered_callbacks)
        
        youtube_filtered_callbacks = {s: c for s, c in (await self.bot.db.get_all_yt_callbacks()).items() if str(ctx.guild.id) in c.alert_roles.keys()}
        await self.youtube_catchup(youtube_filtered_callbacks)
        self.bot.log.info(f"Finished manual server catchup for {ctx.guild.name}")
        await ctx.send(f"{self.bot.emotes.success} Finished server catchup!", ephemeral=True)

    async def twitch_catchup(self, callbacks: Optional[dict[str, Callback]] = None):
        await self.bot.wait_until_ready()
        await self.bot.wait_until_db_ready()
        callbacks = callbacks or await self.bot.db.get_all_callbacks()
        if callbacks == {}:
            return

        # Fetch all streamers, returning the currently live ones
        streams = await self.bot.tapi.get_streams(user_ids=list(callbacks.keys()), origin=AlertOrigin.catchup)
        # We only need the ID from them, as a string due to dict keys only being strings
        online_stream_uids = [str(stream.user.id) for stream in streams]

        # Iterate through all callbacks and update all streamers
        for streamer_id, callback_info in callbacks.items():
            if streamer_id in online_stream_uids:
                stream = [s for s in streams if s.user.id ==
                          int(streamer_id)][0]
                # Update display name if needed
                if callback_info.display_name != stream.user.display_name:
                    callback_info.display_name = stream.user.display_name
                    await self.bot.db.write_callback(stream.user, callback_info)
                self.bot.queue.put_nowait(stream)
            else:
                self.bot.queue.put_nowait(PartialUser(
                    streamer_id, callback_info.display_name.lower(), callback_info.display_name, origin=AlertOrigin.catchup))

    async def youtube_catchup(self, callbacks: Optional[dict[PartialYoutubeUser, YoutubeCallback]] = None):
        await self.bot.wait_until_ready()
        await self.bot.wait_until_db_ready()
        callbacks = callbacks or await self.bot.db.get_all_yt_callbacks()
        if callbacks == {}:
            return

        # Get all caches, saves multiple DB calls for same data
        caches = {c: await self.bot.db.get_yt_channel_cache(c) for c in callbacks.keys()}

        # Offline -> online handling

        # Filter live channels out
        non_live_channels = [c for c in callbacks.keys(
        ) if not caches[c].get("is_live", False)]
        # Fetch recent video IDs from each channel. No API cost. Only check non live channels. Returns dict[channel, list[video_id]]
        recent_vids = await self.bot.yapi.get_recent_video_ids(non_live_channels)
        self.bot.log.debug(f"Recent Video IDs for Channels: {recent_vids}")
        # Returns dict containing each channel as key and video id as value. Return empty dict if none
        new_live_channels = await self.bot.yapi.are_videos_live(recent_vids)
        self.bot.log.debug(f"New Live Channels: {new_live_channels}")

        # Online -> offline handling

        # Fetch all channels that are live. Returns list of video_ids that have ended
        live_videos_cached = [
            caches[c].video_id for c in callbacks.keys() if caches[c].get("is_live", False)]
        ended_videos = await self.bot.yapi.have_videos_ended(live_videos_cached)

        # Iterate through all callbacks and update all streamers
        for channel, callback_info in callbacks.items():
            # If channel is live, check cached video to see if finished
            if channel not in non_live_channels:
                if caches[channel].video_id in ended_videos:
                    channel.origin = AlertOrigin.catchup
                    channel.offline_video_id = caches[channel].video_id
                    self.bot.queue.put_nowait(channel)
                else:
                    # Video requested here purely for title updates
                    try:
                        video = await self.bot.yapi.get_stream(caches[channel].video_id, origin=AlertOrigin.catchup)
                    except (VideoNotFound, VideoNotStream, VideoStreamEnded):
                        continue
                    self.bot.queue.put_nowait(video)
            else:
                # Otherwise, check if channel is live, and fetch video that is live
                if video_id := new_live_channels.get(channel, None):
                    try:
                        video = await self.bot.yapi.get_stream(video_id, origin=AlertOrigin.catchup)
                    except (VideoNotFound, VideoNotStream, VideoStreamEnded):
                        continue
                    if not video:
                        continue
                    # Update display name if needed
                    if callback_info.display_name != video.user.display_name:
                        callback_info.display_name = video.user.display_name
                        await self.bot.db.write_yt_callback(video.user, callback_info)
                    self.bot.queue.put_nowait(video)
                else:
                    channel.origin = AlertOrigin.catchup
                    self.bot.queue.put_nowait(channel)


def setup(bot):
    bot.add_cog(Catchup(bot))
