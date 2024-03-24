from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional, Union

from aiohttp import ClientSession
from aiohttp.client_reqrep import ClientResponse
from bs4 import BeautifulSoup

from .enums import AlertOrigin, YoutubeVideoType
from .exceptions import *
from .subscription import YoutubeSubscription
from .user import PartialYoutubeUser, YoutubeUser
from .video import YoutubeVideo

if TYPE_CHECKING:
    from main import TwitchCallBackBot

LEASE_SECONDS = 828000


class http_youtube:
    def __init__(self, bot, yt_api_key: str, callback_url: str, **kwargs):
        self.bot: TwitchCallBackBot = bot
        self.pubsuburi = "https://pubsubhubbub.appspot.com/subscribe"
        self.base = "https://www.googleapis.com/youtube/v3"
        self.api_key: str = yt_api_key
        self.callback_url: str = callback_url
        self.bot.add_listener(self._make_session, 'on_connect')

    async def _make_session(self):
        self.session: ClientSession = ClientSession()

    async def close_session(self):
        if not self.session.closed:
            await self.session.close()

    async def _request(self, url, method="get", **kwargs):
        if not kwargs.get("no_key", False):
            url = url+f"&key={self.api_key}"
        kwargs.pop("no_key", None)
        response = await self.session.request(method=method, url=url, **kwargs)
        if response.status == 401:  # Refresh access token
            self.bot.log.critical("Invalid access token!")
        return response

    def chunks(self, lst, n):
        """Yield successive n-sized chunks from lst."""
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    async def get_user(self, user: PartialYoutubeUser = None, user_id: str = None, display_name: str = None, user_name: str = None, handle: str = None) -> Optional[YoutubeUser]:
        if user is not None:
            r = await self._request(f"{self.base}/channels?id={user.id}&part=snippet")
        elif user_id is not None:
            r = await self._request(f"{self.base}/channels?id={user_id}&part=snippet")
        elif user_name is not None:
            r = await self._request(f"{self.base}/channels?forUsername={user_name}&part=snippet")
        elif display_name is not None:
            r = await self.scrape_user(f"https://youtube.com/{display_name}")
        elif handle is not None:
            if not handle.startswith("@"):
                handle = f"@{handle}"
            r = await self.scrape_user(f"https://youtube.com/{handle}")
        else:
            raise BadRequest
        if r:
            j = await r.json()
            if j.get("items", []) == []:
                return None
            json_data = j["items"][0]
            return YoutubeUser(**json_data)

    async def scrape_user(self, url: str):
        resp = await self.bot.aSession.get(url)
        soup = BeautifulSoup(await resp.text(), 'html.parser')
        try:
            channel_id = soup.select_one('meta[property="og:url"]')['content'].strip('/').split('/')[-1]
        except TypeError:
            return None
        return await self._request(f"{self.base}/channels?id={channel_id}&part=snippet")

    async def get_channel_upload_playlist_id(self, channel: PartialYoutubeUser) -> Optional[str]:
        r = await self._request(f"{self.base}/channels?id={channel.id}&part=contentDetails")
        rj = await r.json()
        try:
            return rj["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        except KeyError:
            return None

    async def create_subscription(self, channel: PartialYoutubeUser, secret: str, subscription_id: str = None) -> YoutubeSubscription:
        #  For resubscriptions an ID already exists, reuse it
        subscription_id = subscription_id or self.bot.random_string_generator(
            21)
        response = await self._request(self.pubsuburi,
                                       data={
                                           "hub.callback": f"{self.callback_url}/youtube/{channel.id}",
                                           "hub.mode": "subscribe",
                                           "hub.verify": "async",
                                           "hub.lease_seconds": str(LEASE_SECONDS),
                                           "hub.topic": f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel.id}",
                                           "hub.secret": secret,
                                           "hub.verify_token": f"{secret}:{subscription_id}"
                                       }, method="post", no_key=True)
        if response.status not in [202, 204]:
            raise SubscriptionError(
                f"There was an error subscribing to the pubsub. Please try again later. Error code: {response.status}")

        subscription = YoutubeSubscription(subscription_id, channel, secret)

        # Wait for subscription confirmation
        def check(verify_token):
            if verify_token == subscription.id:
                return True
            self.bot.log.warning(f"Bad verify token received for {channel.display_name}")
            return False
        try:
            await self.bot.wait_for("youtube_subscription_confirmation", check=check, timeout=8)
        except asyncio.TimeoutError:
            await self.delete_subscription(subscription)
            raise SubscriptionError(
                "Did not receive subscription confirmation! Please try again later")
        return subscription

    async def delete_subscription(self, subscription: YoutubeSubscription) -> ClientResponse:
        return await self._request(self.pubsuburi,
                                   data={
                                       "hub.callback": f"{self.callback_url}/youtube/{subscription.channel.id}",
                                       "hub.mode": "unsubscribe",
                                       "hub.topic": f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={subscription.channel.id}",
                                       "hub.secret": subscription.secret,
                                       "hub.verify_token": f"{subscription.secret}:{subscription.id}"
                                   }, method="post", no_key=True)

    def is_stream(self, item: dict) -> bool:
        details = item.get("liveStreamingDetails", {})
        if details.get("actualStartTime", None) is not None:
            return True
        return False

    def is_scheduled_stream(self, item: dict) -> bool:
        """Return true if the item is a scheduled stream that hasn't started"""
        details = item.get("liveStreamingDetails", {})
        status = item.get("status", {})
        if details.get("scheduledStartTime", None) is None:
            return False
        if details.get("actualStartTime", None) is not None:
            return False
        if status.get("uploadStatus", None) != "uploaded":
            return False
        return True

    def is_scheduled_premiere(self, item: dict) -> bool:
        """Return true if the item is a scheduled stream that hasn't started"""
        details = item.get("liveStreamingDetails", {})
        status = item.get("status", {})
        if details.get("scheduledStartTime", None) is None:
            return False
        if details.get("actualStartTime", None) is not None:
            return False
        if status.get("uploadStatus", None) != "processed":
            return False
        return True

    def has_stream_ended(self, item: dict) -> bool:
        details = item.get("liveStreamingDetails", {})
        if details.get("actualEndTime", None):
            return True
        return False

    # Iffy check, needs confirmation
    def is_premiere(self, item: dict) -> bool:
        status_details = item.get("status", {})
        # uploadStatus will be "uploaded" when it is a live stream
        #self.bot.log.info(f"{item['id']} Is premiere: {'Yes' if status_details['uploadStatus'] == 'processed' else 'No'}. Upload status: {item['status']['uploadStatus']}")
        if status_details["uploadStatus"] == "processed":
            return True
        return False

    def get_video_type(self, item: dict) -> YoutubeVideoType:
        video_type = "video"
        if self.is_stream(item):
            video_type = "stream"
            if self.is_premiere(item):
                video_type = "premiere"
        if self.is_scheduled_stream(item):
            video_type = "scheduled_stream"
        if self.is_scheduled_premiere(item):
            video_type = "scheduled_premiere"
        return YoutubeVideoType(video_type)

    async def has_video_ended(self, video_id: str) -> Union[str, bool]:
        """Returns the end date if the provided stream has ended, otherwise returns false"""
        stream = await self._request(f"{self.base}/videos?id={video_id}&part=liveStreamingDetails")
        stream_json = await stream.json()
        # Check if video is a stream first
        if stream_json.get("items", []) != []:
            if self.is_stream(stream_json["items"][0]) and self.has_stream_ended(stream_json["items"][0]):
                return stream_json["items"][0]["liveStreamingDetails"]["actualEndTime"]
        return False

    async def have_videos_ended(self, video_ids: list[str]) -> list[str]:
        ended_videos = []
        all_ids = []
        for chunk in self.chunks(video_ids, 50):
            stream = await self._request(f"{self.base}/videos?id={','.join(chunk)}&part=liveStreamingDetails,status")
            stream_json = await stream.json()
            for item in stream_json.get("items", []):
                if self.is_stream(item) and self.has_stream_ended(item):
                    ended_videos.append(item["id"])
                all_ids.append(item["id"])
        for id in video_ids:
            if id not in all_ids:
                ended_videos.append(id)
        return ended_videos

    async def get_stream(self, video_id: str, origin: AlertOrigin = AlertOrigin.callback) -> Optional[YoutubeVideo]:
        stream = await self._request(f"{self.base}/videos?id={video_id}&part=liveStreamingDetails,status")
        stream_json = await stream.json()
        # Check if video is a stream first
        if stream_json.get("items", []) != []:
            item = stream_json["items"][0]
            video_type = self.get_video_type(item)
            # self.bot.log.info(f"Scheduled Stream: {self.is_scheduled_stream(item)}")
            if video_type == YoutubeVideoType.video:
                raise VideoNotStream(video_id, video_type=video_type.value)
            if self.has_stream_ended(item):
                raise VideoStreamEnded(video_id)
        else:
            raise VideoNotFound(video_id)
        # Fetch more info if stream is live
        snippet_content = await self._request(f"{self.base}/videos?id={video_id}&part=snippet,contentDetails")
        snippet_content_json = await snippet_content.json()
        # Pass requests to video class
        return YoutubeVideo(video_id,
                            snippet_content_json["items"][0]["snippet"],
                            snippet_content_json["items"][0]["contentDetails"],
                            item["status"],
                            item["liveStreamingDetails"], video_type=video_type, origin=origin)
    
    async def get_video(self, video_id: str, origin: AlertOrigin = AlertOrigin.unavailable) -> Optional[YoutubeVideo]:
        stream = await self._request(f"{self.base}/videos?id={video_id}&part=liveStreamingDetails,status")
        stream_json = await stream.json()
        # Check if video is a stream first
        if stream_json.get("items", []) != []:
            item = stream_json["items"][0]
            video_type = self.get_video_type(item)
        else:
            raise VideoNotFound(video_id)
        # Fetch more info if stream is live
        snippet_content = await self._request(f"{self.base}/videos?id={video_id}&part=snippet,contentDetails")
        snippet_content_json = await snippet_content.json()
        # Pass requests to video class
        return YoutubeVideo(video_id,
                            snippet_content_json["items"][0]["snippet"],
                            snippet_content_json["items"][0]["contentDetails"],
                            item["status"],
                            item["liveStreamingDetails"], video_type=video_type, origin=origin)

    async def parse_video_xml(self, channel: PartialYoutubeUser, request_content: str) -> Optional[YoutubeVideo]:
        soup = BeautifulSoup(request_content, features="xml")

        display_name = soup.find_all('name')[0].text
        try:
            id = soup.find_all("yt:videoid")[0].text
        except IndexError:  # This is a video deletion/unpublish message, ignore
            deleted_video_id = soup.find("link")["href"].split("watch?v=")[-1]
            channel_cache = await self.bot.db.get_yt_channel_cache(channel)
            if channel_cache.is_live and channel_cache.video_id == deleted_video_id:
                channel.origin = AlertOrigin.callback
                self.bot.queue.put_nowait(channel)
            self.bot.log.info(
                f"[Youtube] {display_name} deleted video {deleted_video_id}")
            return
        #channel_id = soup.find_all("yt:channelid")[0].text

        last_vid = await self.bot.db.get_last_yt_vid(channel) or {}
        last_vid_id: str = last_vid.get("video_id", None)
        last_vid_publish_time: int = last_vid.get("publish_time", 0)

        # Check video in cache
        if id == last_vid_id:
            self.bot.log.info(
                f"[Youtube] {display_name} updated latest video {id}")
            try:
                return await self.get_stream(id)
            except (VideoNotFound, VideoNotStream, VideoStreamEnded) as e:
                self.bot.log.info(f"[Youtube] {display_name}: {str(e)}")
                return

        # Check video exists
        try:
            video = await self.get_stream(id)
        except (VideoNotFound, VideoNotStream, VideoStreamEnded) as e:
            self.bot.log.info(f"[Youtube] {display_name}: {str(e)}")
            return

        if video.published_at.timestamp() < last_vid_publish_time:
            self.bot.log.info(
                f"[Youtube] {display_name} updated older video with {id}, ignoring")
            return

        await self.bot.db.update_last_yt_vid(video)

        self.bot.log.debug(
            f"[Youtube] {id} new {video.type} for {display_name}")

        return video

    async def is_channel_live(self, channel: PartialYoutubeUser) -> Optional[str]:
        if ids := (await self.get_recent_video_ids(channel)).get(channel, None):
            stream = await self._request(f"{self.base}/videos?id={','.join(ids)}&part=liveStreamingDetails,status")
            stream_json = await stream.json()
            # Check if video is a stream and return ID if so
            for item in stream_json["items"]:
                if self.is_stream(item) and not self.has_stream_ended(item):
                    return item["id"]
        return None

    async def get_recent_video_ids(self, channels: list[PartialYoutubeUser]) -> dict[PartialYoutubeUser, list[str]]:
        ids_dict: dict[PartialYoutubeUser, list[str]] = {}
        if type(channels) != list:
            channels = [channels]
        for channel in channels:
            callback = await self.bot.db.get_yt_callback(channel)
            r = await self.bot.aSession.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel.id}")
            soup = BeautifulSoup(await r.read(), features="xml")
            # Read the most recent 2 entries and extract the video IDs
            ids_search = soup.find_all("yt:videoid")
            ids_dict[channel] = [id.text for id in ids_search]
            if playlist_id := callback.get("uploads_playlist_id", None):
                try:
                    r = await self._request(f"{self.base}/playlistItems?playlistId={playlist_id}&part=contentDetails")
                    rj = await r.json()
                    api_ids = [item["contentDetails"]["videoId"]
                               for item in rj.get("items", [])]
                    for id in api_ids:
                        if id not in ids_dict[channel]:
                            ids_dict[channel].append(id)
                except Exception as e:
                    self.bot.log.error(
                        f"Exception fetching uploads playlist for {channel.display_name}: {str(e)}")
        return ids_dict

    async def are_videos_live(self, video_ids: dict[PartialYoutubeUser, list[str]]) -> dict[PartialYoutubeUser, str]:
        live_channels = {}
        all_ids = []
        for ids in video_ids.values():
            all_ids += ids
        for chunk in self.chunks(all_ids, 50):
            stream = await self._request(f"{self.base}/videos?id={','.join(chunk)}&part=liveStreamingDetails,status")
            stream_json = await stream.json()
            # Check if video is a stream and return ID if so
            for item in stream_json["items"]:
                video_type = self.get_video_type(item)
                if video_type != YoutubeVideoType.video and not self.has_stream_ended(item):
                    for c, v in video_ids.items():
                        if item["id"] in v:
                            channel = c
                    live_channels[channel] = item["id"]
        return live_channels
