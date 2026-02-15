from re import findall

from disnake.ext import commands


class Asset:
    def __init__(self, avatar: str):
        self.BASE = "https://static-cdn.jtvnw.net/"
        self._raw_url = avatar
        self.__size: tuple[str, str] = tuple(findall(r"(image|(live_user.*))-(.*)(\.png|\.jpeg|\.jpg)", self._raw_url)[0][-2].split("x"))
        self.url: str = self._raw_url.replace(f"{self.__size[0]}x{self.__size[1]}", "{width}x{height}")

    def __str__(self) -> str:
        return self._raw_url

    def __eq__(self, other):
        return isinstance(other, Asset) and self._raw_url == other._raw_url

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self._raw_url.replace(self.BASE, '')}>"

class Avatar(Asset):
    def __init__(self, avatar: str):
        super().__init__(avatar)

    def within_range(self, size: int):
        return True if size in (300, 600) else False

    def with_size(self, size: int):
        if not self.within_range(size):
            raise commands.BadArgument("Size must be 300 or 600!")
        return Avatar(self.url.format(width=size, height=size))

class OfflineImage(Asset):
    def __init__(self, avatar: str):
        super().__init__(avatar)
    
    def within_range(self, width: int, height: int):
        if width > 2048 or width < 1:
            return False
        if height > 2048 or height < 1:
            return False
        return True

    def with_size(self, width: int, height: int):
        if not self.within_range(width, height):
            raise commands.BadArgument("Size must be not be smaller than 1 or greater than 2048")
        return OfflineImage(self.url.format(width=width, height=height))

class Thumbnail(OfflineImage):
    def __init__(self, avatar: str):
        super().__init__(avatar)

    def with_size(self, width: int, height: int):
        if not self.within_range(width, height):
            raise commands.BadArgument("Size must be not be smaller than 1 or greater than 2048")
        return Thumbnail(self.url.format(width=width, height=height))