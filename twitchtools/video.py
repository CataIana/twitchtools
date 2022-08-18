from .user import PartialUser
from .enums import Languages, VideoType, VideoPrivacy
from dateutil import parser
from typing import Optional

class Video:
    def __init__(self, id, stream_id, user_id, user_login, user_name, title, description, created_at, published_at, url, thumbnail_url, viewable, view_count, language, type, duration, muted_segments):
        self.id: int = int(id)
        self.video_id: int = self.id
        self.stream_id = int(stream_id)
        self.user = PartialUser(user_id, user_login, user_name)
        self.title: str = title
        self.description: Optional[str] = description if description else None
        self.created_at = parser.parse(created_at)
        self.published_at = parser.parse(published_at)
        self.url: str = url
        self.thumbnail_url: Optional[str] = thumbnail_url if thumbnail_url else None
        self.viewable: str = VideoPrivacy(viewable)
        self.view_count: int = int(view_count)
        try:
            self.language: Languages = Languages[language.upper()]
        except KeyError:
            self.language: Languages = Languages.OTHER
        self.type = VideoType[type]
        self.duration: str = duration
        self.muted_segments: Optional[list[dict[str]]] = muted_segments
        
    def __repr__(self) -> str:
        return f'<{type(self).__name__} id={self.id} user={self.user.login!r}>'

    def __eq__(self, other):
        return isinstance(other.__class__, self.__class__) and self.id == other.id
