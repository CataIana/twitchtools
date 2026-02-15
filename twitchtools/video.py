from datetime import datetime
from typing import Optional, Union

from dateutil import parser

from .enums import (AlertOrigin, Languages, VideoPrivacy, VideoType,
                    YoutubeVideoType, MutedSegments)
from .user import PartialUser, PartialYoutubeUser, YoutubeUser


def get_total_seconds(string: str):
    convs = {"D": 86400, "H": 3600, "M": 60, "S": 1}
    total = 0
    capture = ""
    for i in range(len(string)):
        # Check if char is an int and capture all until there is a char
        if string[i].isnumeric():
            capture += string[i]
        # Multiply captured numbers depending on suffix
        elif multiply := convs.get(string[i].upper()):
            total += int(capture)*multiply
            capture = ""
    return total

class Video:
    def __init__(self, id, stream_id, user_id, user_login, user_name, title, description, created_at, published_at, url, thumbnail_url, viewable, view_count, language, type, duration, muted_segments):
        self.id: int = int(id)
        self.video_id: int = self.id
        self.stream_id = int(stream_id)
        self.user = PartialUser(user_id, user_login, user_name)
        self.title: str = title
        self.description: Optional[str] = description or None
        self.created_at = parser.parse(created_at)
        self.published_at = parser.parse(published_at)
        self.url: str = url
        self.thumbnail_url: Optional[str] = thumbnail_url or None
        self.viewable = VideoPrivacy(viewable)
        self.view_count: int = int(view_count)
        try:
            self.language: Languages = Languages[language.upper()]
        except KeyError:
            self.language: Languages = Languages.OTHER
        self.type = VideoType[type]
        self.duration: int = get_total_seconds(duration)
        self.muted_segments: Optional[list[MutedSegments]] = muted_segments
        
    def __repr__(self) -> str:
        return f'<{type(self).__name__} id={self.id} user={self.user.login!r}>'

    def __eq__(self, other):
        return isinstance(other.__class__, self.__class__) and self.id == other.id


class YoutubeVideo:
    def __init__(self, id: str, snippet: dict, content: dict, status: dict, stream: dict, video_type: YoutubeVideoType, origin: AlertOrigin, **kwargs):
        self.id: str = id
        self.video_id: str = self.id
        self.channel = PartialYoutubeUser(
            snippet["channelId"], snippet["channelTitle"])
        self.user: Union[PartialYoutubeUser, YoutubeUser] = self.channel
        self.title: str = snippet["title"]
        self.description: Optional[str] = snippet["description"] or None
        self.published_at = parser.parse(snippet["publishedAt"])
        self.url: str = f"https://youtube.com/watch?v={self.id}"
        self.thumbnail_url: Optional[str] = snippet["thumbnails"][list(
            snippet["thumbnails"].keys())[-1]]["url"]
        self.tags: list[str] = snippet.get("tags", [])
        self.category_id: int = int(snippet["categoryId"])
        self.duration: int = get_total_seconds(content["duration"])
        self.is_live: bool = True if snippet.get(
            "liveBroadcastContent", None) == "live" else False
        if stream.get("actualStartTime", None):
            self.started_at: Optional[datetime] = parser.parse(stream["actualStartTime"])
        else:
            self.started_at: Optional[datetime] = None
        if stream.get("scheduledStartTime", None):
            self.scheduled_at: Optional[datetime] = parser.parse(stream["scheduledStartTime"])
        else:
            self.scheduled_at: Optional[datetime] = None
        self.created_at = self.started_at
        self.view_count: Optional[int] = int(stream.get("concurrentViewers", 0)) or None
        self.origin: AlertOrigin = origin
        self.upload_status: str = status["uploadStatus"]
        self.privacy_status: str = status["privacyStatus"]
        self.made_for_kids: bool = status["madeForKids"]
        self.embeddable: bool = status["embeddable"]
        self.type: YoutubeVideoType = video_type

    def __repr__(self) -> str:
        return f'<{type(self).__name__} id={self.id} user={self.user.display_name!r}>'

    def __eq__(self, other):
        return isinstance(other.__class__, self.__class__) and self.id == other.id
