from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional, Union

from aiohttp import ClientSession
from aiohttp.client_reqrep import ClientResponse
from bs4 import BeautifulSoup

from .enums import AlertOrigin
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

    async def get_user(self, user: PartialYoutubeUser = None, user_id: str = None, display_name: int = None) -> Optional[YoutubeUser]:
        if user is not None:
            r = await self._request(f"{self.base}/channels?id={user.id}&part=snippet")
        elif user_id is not None:
            r = await self._request(f"{self.base}/channels?id={user_id}&part=snippet")
        elif display_name is not None:
            resp = await self.bot.aSession.get(f"https://youtube.com/{display_name}")
            soup = BeautifulSoup(await resp.text(), 'html.parser')
            try:
                channel_id = soup.select_one('meta[property="og:url"]')[
                    'content'].strip('/').split('/')[-1]
            except TypeError:
                return None
            r = await self._request(f"{self.base}/channels?id={channel_id}&part=snippet")
            # r = await self._request(f"{self.base}/users?login={user_login}")
        else:
            raise BadRequest
        j = await r.json()
        if j.get("items", []) == []:
            return None
        json_data = j["items"][0]
        return YoutubeUser(**json_data)

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

    def has_stream_ended(self, item: dict) -> bool:
        details = item.get("liveStreamingDetails", {})
        if details.get("actualEndTime", None):
            return True
        return False

    async def has_video_ended(self, video_id: str) -> Union[str, bool]:
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
            stream = await self._request(f"{self.base}/videos?id={','.join(chunk)}&part=liveStreamingDetails")
            stream_json = await stream.json()
            for item in stream_json.get("items", []):
                if self.is_stream(item) and self.has_stream_ended(item):
                    ended_videos.append(item["id"])
                all_ids.append(item["id"])
        for id in video_ids:
            if id not in all_ids:
                ended_videos.append(id)
        return ended_videos

    async def get_stream(self, video_id: str, alert_origin: AlertOrigin = AlertOrigin.callback) -> Optional[YoutubeVideo]:
        stream = await self._request(f"{self.base}/videos?id={video_id}&part=liveStreamingDetails")
        stream_json = await stream.json()
        # Check if video is a stream first
        if stream_json.get("items", []) != []:
            if not self.is_stream(stream_json["items"][0]):
                return None
        else:
            return None
        # Fetch more info if stream is live
        snippet_content = await self._request(f"{self.base}/videos?id={video_id}&part=snippet,contentDetails")
        snippet_content_json = await snippet_content.json()
        # Pass requests to video class
        return YoutubeVideo(video_id,
                            snippet_content_json["items"][0]["snippet"],
                            snippet_content_json["items"][0]["contentDetails"],
                            stream_json["items"][0].get("liveStreamingDetails", None), alert_origin=alert_origin)

    async def parse_video_xml(self, channel: PartialYoutubeUser, request_content: str) -> Optional[YoutubeVideo]:
        soup = BeautifulSoup(request_content, "lxml")

        display_name = soup.find_all('name')[0].text
        try:
            id = soup.find_all("yt:videoid")[0].text
        except IndexError:  # This is a video deletion/unpublish message, ignore
            self.bot.log.info(
                f"{display_name} deleted a video, ignoring.")
            return None
        #channel_id = soup.find_all("yt:channelid")[0].text

        last_vid = await self.bot.db.get_last_yt_vid(channel) or {}
        last_vid_id: str = last_vid.get("video_id", None)
        last_vid_publish_time: int = last_vid.get("publish_time", 0)

        # Check video in cache
        if id == last_vid_id:
            self.bot.log.info(
                f"{display_name} updated latest video, ignoring.")
            return await self.get_stream(id)

        # Check video exists
        video = await self.get_stream(id)
        if video is None:
            self.bot.log.info(
                f"Video from {display_name} doesn't exist or is not a stream, ignoring.")
            return None

        if video.published_at.timestamp() < last_vid_publish_time:
            self.bot.log.info(
                f"{video.channel.display_name} updated a video, ignoring.")
            return None

        await self.bot.db.update_last_yt_vid(video)

        self.bot.log.debug(
            f"Youtube stream confirmed as new for {video.channel.display_name}")

        return video

    async def is_channel_live(self, channel: PartialYoutubeUser) -> Optional[str]:
        if ids := (await self.get_recent_video_ids(channel)).get(channel, None):
            stream = await self._request(f"{self.base}/videos?id={','.join(ids)}&part=liveStreamingDetails")
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
            soup = BeautifulSoup(await r.read(), "lxml")
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
            stream = await self._request(f"{self.base}/videos?id={','.join(chunk)}&part=liveStreamingDetails")
            stream_json = await stream.json()
            # Check if video is a stream and return ID if so
            for item in stream_json["items"]:
                if self.is_stream(item) and not self.has_stream_ended(item):
                    for c, v in video_ids.items():
                        if item["id"] in v:
                            channel = c
                    live_channels[channel] = item["id"]
        return live_channels
