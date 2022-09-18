from datetime import datetime

from dateutil import parser

from .enums import (Languages, SubscriptionMethod, SubscriptionStatus,
                    SubscriptionType)
from .user import PartialUser, PartialYoutubeUser


class YoutubeSubscription:
    def __init__(self, id: str, channel: PartialYoutubeUser, secret: str):
        self.id: str = id
        self.channel: PartialYoutubeUser = channel
        self.secret: str = secret

class Subscription:
    def __init__(self, id: str, status: str, type: str, version: int, condition: dict, created_at: str, transport: dict, cost: int):
        self.id: str = id
        self.status: SubscriptionStatus = SubscriptionStatus(status)
        self.type: SubscriptionType = SubscriptionType(type)
        self.version: int = int(version)
        self.broadcaster_user_id: int = int(condition["broadcaster_user_id"])
        self.created_at: datetime = parser.parse(created_at)
        self.method: SubscriptionMethod = SubscriptionMethod(transport["method"])
        self.callback: str = transport["callback"]
        self.cost: int = int(cost)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id} broadcaster_id={self.broadcaster_user_id} callback={self.callback}>"

class SubscriptionEvent(Subscription):
    def __init__(self, **kwargs):
        self._subscription = kwargs["subscription"]
        self._event = kwargs["event"]
        super().__init__(**kwargs["subscription"])
        self.broadcaster = PartialUser(user_id=self._event["broadcaster_user_id"], user_login=self._event["broadcaster_user_login"], display_name=self._event["broadcaster_user_name"])

    def __repr__(self):
        return f"<SubscriptionEvent broadcaster={self.broadcaster.username} type={self.type}>"

class TitleEvent(SubscriptionEvent):
    def __init__(self, **kwargs):
        event = kwargs["event"]
        super().__init__(**kwargs)
        self.title = "<no title>" if event["title"] == "" else event["title"]
        self.stream_title = self.title
        try:
            self.language: Languages = Languages[event["language"].upper()]
        except KeyError:
            self.language: Languages = Languages.OTHER
        self.game = "<no game>" if event["category_name"] == "" else event["category_name"]
        self.game_name = self.game
        self.game_id = event["category_id"]

