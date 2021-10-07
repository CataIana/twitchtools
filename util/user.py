from dateutil import parser
from util.asset import Avatar, OfflineImage
from util.enums import UserType, BroadcasterType
from datetime import datetime

class PartialUser:
    def __init__(self, user_id, user_login, display_name):
        self.user_id = int(user_id)
        self.id = int(user_id)
        self.login = user_login
        self.name = user_login
        self.username = user_login
        self.display_name = display_name
        
    def __repr__(self) -> str:
        return f'<User id={self.id} name={self.name!r}>'

    def __eq__(self, other):
        return isinstance(other, User) and self.id == other.id


class User(PartialUser):
    def __init__(self, id: int, login: str, display_name: str, type: UserType, broadcaster_type: BroadcasterType,
                description: str, profile_image_url: str, offline_image_url: str, view_count: int, created_at: datetime):
        super().__init__(id, login, display_name)
        self.display_name = display_name
        self.user_type = UserType(type)
        self.type = UserType(type)
        self.broadcaster_type = BroadcasterType(broadcaster_type)
        self.user_description = None if description == "" else description
        self.description = None if description == "" else description
        if profile_image_url != "":
            self.avatar = Avatar(profile_image_url)
        else:
            self.avatar = None
        if offline_image_url != "":
            self.offline_image = OfflineImage(offline_image_url)
        else:
            self.offline_image = None
        self.view_count = int(view_count)
        self.created_at = parser.parse(created_at)
