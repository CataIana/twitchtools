from dateutil import parser
from .asset import Avatar, OfflineImage
from .enums import UserType, BroadcasterType
from datetime import datetime
from typing import Union

class PartialUser:
    def __init__(self, user_id, user_login, display_name):
        self.user_id: int = int(user_id)
        self.id: int = int(user_id)
        self.login: str = user_login
        self.name: str = user_login
        self.username: str = user_login
        self.display_name: str = display_name

    def __str__(self) -> str:
        return self.login
        
    def __repr__(self) -> str:
        return f'<User id={self.id} name={self.name!r}>'

    def __eq__(self, other):
        return isinstance(other, User) and self.id == other.id


class User(PartialUser):
    def __init__(self, id: int, login: str, display_name: str, type: UserType, broadcaster_type: BroadcasterType,
                description: str, profile_image_url: str, offline_image_url: str, view_count: int, created_at: datetime):
        super().__init__(id, login, display_name)
        self.user_type: UserType = UserType(type)
        self.type: UserType = UserType(type)
        self.broadcaster_type: BroadcasterType = BroadcasterType(broadcaster_type)
        self.user_description: Union[str, None] = None if description == "" else description
        self.description = None if description == "" else description
        self.avatar: Union[Avatar, None] = None if profile_image_url == "" else Avatar(profile_image_url)
        self.offline_image: Union[OfflineImage, None] = None if offline_image_url == "" else OfflineImage(offline_image_url)
        self.view_count: int = int(view_count)
        self.created_at: datetime = parser.parse(created_at)
