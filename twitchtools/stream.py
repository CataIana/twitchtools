from datetime import datetime
from typing import Optional, Union

from dateutil import parser

from .asset import Thumbnail
from .enums import AlertOrigin, Languages, Live
from .user import PartialUser, User


class Stream:
    def __init__(self, id: int, user_id: int, user_login: str, user_name: str, game_id: int,
                 game_name: str, type: Live, title: str, viewer_count: int, started_at: str,
                 language: str, thumbnail_url: str, tag_ids: list[str], tags: list[str], is_mature: bool, origin: AlertOrigin = AlertOrigin.unavailable):
        self.stream_id: int = int(id)
        self.id: int = id
        self.user: Union[PartialUser, User] = PartialUser(
            user_id, user_login, user_name)
        self.game_id: Optional[int] = int(game_id) if game_id != '' else None
        self.game: str = "<no game>" if game_name == "" else game_name
        self.game_name: str = self.game
        self.type: Live = Live(type)
        self.title: str = "<no title>" if title == "" else title
        self.stream_title: str = self.title
        self.viewer_count: int = int(viewer_count)
        self.view_count: int = self.viewer_count
        self.views: int = self.viewer_count
        self.started_at: datetime = parser.parse(started_at)
        try:
            self.language: Languages = Languages[language.upper()]
        except KeyError:
            self.language: Languages = Languages.OTHER
        self.thumbnail_url: Thumbnail = Thumbnail(thumbnail_url)
        self.tag_ids: list[str] = tag_ids
        self.tags: list[str] = tags
        self.is_mature: bool = bool(is_mature)
        self.origin: AlertOrigin = origin

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} streamer={self.user} game={self.game} stream_id={self.id}>"
