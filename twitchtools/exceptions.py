from disnake.ext import commands


class TwitchToolsException(commands.CommandError):
    pass


class BadAuthorization(TwitchToolsException):
    def __init__(self, message: str = ""):
        super().__init__(
            f"Bad authorization! Please check your configuration{f': {message}' if message else ''}")


class BadRequest(TwitchToolsException):
    pass


class SubscriptionError(TwitchToolsException):
    def __init__(self, message: str = ""):
        super().__init__(message or "There was an error handling the eventsub subscription")


class RateLimitExceeded(TwitchToolsException):
    def __init__(self, display_name: str, when: int):
        super().__init__(
            f"Ratelimit exceeded for {display_name}! Wait {when} second{'s' if when != 1 else ''}")


class DBConnectionError(TwitchToolsException):
    def __init__(self, message: str = ""):
        super().__init__(message or "Not connected to database!")

class VideoNotFound(TwitchToolsException):
    def __init__(self, video_id: str):
        super().__init__(f"Video {video_id} not found")

class VideoNotStream(TwitchToolsException):
    def __init__(self, video_id: str, video_type: str):
        super().__init__(f"Video {video_id} is a {video_type}")

class VideoStreamEnded(TwitchToolsException):
    def __init__(self, video_id: str):
        super().__init__(f"Video {video_id} is a livestream that has already ended")