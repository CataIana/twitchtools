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
        self.stream_id = int(id)
        self.id = id
        self.user = PartialUser(user_id, user_login, user_name)
        self.game_id = int(game_id)
        self.game = game_name
        self.game_name = game_name
        self.type = Live(type)
        self.stream_title = title
        self.title = title
        self.viewer_count = int(viewer_count)
        self.view_count = int(viewer_count)
        self.views = int(viewer_count)
        self.started_at = parser.parse(started_at)
        try:
            self.language = Languages[language.upper()]
        except KeyError:
            self.language = Languages.OTHER
        self.thumbnail_url = Thumbnail(thumbnail_url)
        self.tag_ids = tag_ids
        self.is_mature = bool(is_mature)

