from datetime import datetime
from typing import Optional

from dateutil import parser

from .asset import Avatar, OfflineImage
from .enums import AlertOrigin, BroadcasterType, UserType


class PartialUser:
    def __init__(self, user_id, user_login, display_name, origin: Optional[AlertOrigin] = None):
        self.user_id: int = int(user_id)
        self.id: int = int(user_id)
        self.login: str = user_login
        self.name: str = user_login
        self.username: str = user_login
        self.display_name: str = display_name
        self.origin: Optional[AlertOrigin] = origin

    def __str__(self) -> str:
        return self.login
        
    def __repr__(self) -> str:
        return f'<User id={self.id} name={self.name!r}>'

    def __eq__(self, other):
        return isinstance(other, User) and self.id == other.id


class PartialYoutubeUser:
    def __init__(self, user_id: str, display_name: str, origin: Optional[AlertOrigin] = AlertOrigin.unavailable):
        self.user_id: str = user_id
        self.id: str = user_id
        self.display_name: str = display_name
        self.origin: AlertOrigin = origin
        self.offline_video_id: Optional[str]

    def __str__(self) -> str:
        return self.display_name

    def __repr__(self) -> str:
        return f'<User id={self.id} name={self.display_name!r}>'

    def __eq__(self, other):
        return isinstance(other, User) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


class User(PartialUser):
    def __init__(self, id: int, login: str, display_name: str, type: UserType, broadcaster_type: BroadcasterType,
                description: str, profile_image_url: str, offline_image_url: str, view_count: int, created_at: str):
        super().__init__(id, login, display_name)
        self.user_type: UserType = UserType(type)
        self.type: UserType = UserType(type)
        self.broadcaster_type: BroadcasterType = BroadcasterType(broadcaster_type)
        self.user_description: Optional[str] = None if description == "" else description
        self.description = None if description == "" else description
        self.avatar: Optional[Avatar] = None if profile_image_url == "" else Avatar(profile_image_url)
        self.offline_image: Optional[OfflineImage] = None if offline_image_url == "" else OfflineImage(offline_image_url)
        self.view_count: int = int(view_count)
        self.created_at: datetime = parser.parse(created_at)


class YoutubeUser(PartialYoutubeUser):
    def __init__(self, id: str, snippet: dict, **kwargs):
        super().__init__(id, snippet["title"])
        self.description: str = snippet["description"]
        self.avatar_url: str = snippet["thumbnails"]["high"]["url"]
