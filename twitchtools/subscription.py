from datetime import datetime
from dateutil import parser
from .enums import SubscriptionStatus

class Subscription:
    def __init__(self, id: str, status: str, type: str, version: int, condition: dict, created_at: datetime, transport: dict, cost: int):
        self.id = id
        self.status = SubscriptionStatus(status)
        self.type = type
        self.version = int(version)
        self.broadcaster_user_id = condition["broadcaster_user_id"]
        self.created_at = parser.parse(created_at)
        self.method = transport["method"]
        self.callback = transport["callback"]
        self.cost = int(cost)