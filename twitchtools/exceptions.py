from disnake.ext import commands


class TwitchToolsException(commands.CommandError):
    pass


class BadAuthorization(TwitchToolsException):
    def __init__(self, message: str = None):
        super().__init__(
            f"Bad authorization! Please check your configuration{f': {message}' if message else ''}")


class BadRequest(TwitchToolsException):
    pass


class SubscriptionError(TwitchToolsException):
    def __init__(self, message=None):
        super().__init__(message or "There was an error handling the eventsub subscription")


class RateLimitExceeded(TwitchToolsException):
    def __init__(self, display_name, when):
        super().__init__(
            f"Ratelimit exceeded for {display_name}! Wait {when} second{'s' if when != 1 else ''}")


class DBConnectionError(TwitchToolsException):
    def __init__(self, message: str = None):
        super().__init__(message or "Not connected to database!")
