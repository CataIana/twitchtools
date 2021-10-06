from dislash.application_commands.errors import ApplicationCommandError


class TwitchToolsException(ApplicationCommandError):
    pass

class BadAuthorization(TwitchToolsException):
    def __init__(self):
        super().__init__("Bad authorization! Please check your configuration.")

class HTTPException(TwitchToolsException):
    pass

class BadRequest(TwitchToolsException):
    pass

class SubscriptionError(TwitchToolsException):
    def __init__(self, message = None):
        super().__init__(message or "There was an error handling the eventsub subscription")