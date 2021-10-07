from datetime import datetime
from dateutil import parser
from .enums import SubscriptionStatus, SubscriptionType

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