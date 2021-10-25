from re import findall
from .exceptions import BadArgument

class Asset:
    def __init__(self, avatar, size=None):
        self.BASE = "https://static-cdn.jtvnw.net/"
        self._url = avatar
        self.size: str = size or tuple(findall(r"(image|(live_user.*))-(.*)(\.png|\.jpeg|\.jpg)", self._url)[0][-2].split("x"))
        self.url: str = self._url.replace(f"{self.size[0]}x{self.size[1]}", "{width}x{height}")  

    def __str__(self) -> str:
        return self._url

    def __eq__(self, other):
        return isinstance(other, Asset) and self._url == other._url

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self._url.replace(self.BASE, '')}>"

class Avatar(Asset):
    def __init__(self, avatar, size=None):
        super().__init__(avatar, size)

    @classmethod
    def within_range(self, size) :
        return True if size in (300, 600) else False

    def with_size(self, size):
        if not self.within_range(size):
            raise BadArgument("Size must be 300 or 600!")
        return Avatar(self.url.format(width=size, height=size), size=size)

class OfflineImage(Asset):
    def __init__(self, avatar, size=None):
        super().__init__(avatar, size)
    
    @classmethod
    def within_range(self, width, height):
        if width > 2048 or width < 1:
            return False
        if height > 2048 or height < 1:
            return False
        return True

    def with_size(self, width, height):
        if not self.within_range(width, height):
            raise BadArgument("Size must be not be smaller than 1 or greater than 2048")
        return OfflineImage(self.url.format(width=width, height=height), size=(width, height))

class Thumbnail(OfflineImage):
    def __init__(self, avatar, size=None):
        super().__init__(avatar, size)

    def with_size(self, width, height):
        if not self.within_range(width, height):
            raise BadArgument("Size must be not be smaller than 1 or greater than 2048")
        return Thumbnail(self.url.format(width=width, height=height), size=(width, height))