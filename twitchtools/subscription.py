from datetime import datetime
from dateutil import parser
from .enums import SubscriptionStatus, SubscriptionType, Languages
from .user import PartialUser

class Subscription:
    def __init__(self, id: str, status: str, type: str, version: int, condition: dict, created_at: datetime, transport: dict, cost: int):
        self.id: str = id
        self.status: SubscriptionStatus = SubscriptionStatus(status)
        self.type: SubscriptionType = SubscriptionType(type)
        self.version: int = int(version)
        self.broadcaster_user_id: int = int(condition["broadcaster_user_id"])
        self.created_at: datetime = parser.parse(created_at)
        self.method: str = transport["method"]
        self.callback: str = transport["callback"]
        self.cost: int = int(cost)

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

