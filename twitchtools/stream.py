from datetime import datetime
from dateutil import parser
from .enums import Live, Languages
from datetime import datetime
from .user import PartialUser
from .asset import Thumbnail

class Stream:
    def __init__(self, id: int, user_id: int, user_login: str, user_name: str, game_id: int,
                    game_name: str, type: Live, title: str, viewer_count: int, started_at: datetime,
                    language: Languages, thumbnail_url: str, tag_ids: list, is_mature: bool):
        self.stream_id: int = int(id)
        self.id: int = id
        self.user: PartialUser = PartialUser(user_id, user_login, user_name)
        self.game_id: int = int(game_id)
        self.game: str = game_name
        self.game_name: str = game_name
        self.type: Live = Live(type)
        self.stream_title: str = title
        self.title: str = title
        self.viewer_count: int = int(viewer_count)
        self.view_count: int = int(viewer_count)
        self.views: int = int(viewer_count)
        self.started_at: datetime = parser.parse(started_at)
        try:
            self.language: Languages = Languages[language.upper()]
        except KeyError:
            self.language: Languages = Languages.OTHER
        self.thumbnail_url: Thumbnail = Thumbnail(thumbnail_url)
        self.tag_ids: list = tag_ids
        self.is_mature: bool = bool(is_mature)
