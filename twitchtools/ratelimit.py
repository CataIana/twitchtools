from time import time
from asyncio import iscoroutinefunction
from functools import wraps
from twitchtools.exceptions import RateLimitExceeded

class Ratelimit:
    def __init__(self, calls: int, period: int):
        self.calls = calls # How many calls per period
        self.period = period # How many seconds before reset

        self._requests_in_period = 0
        self._reset_time = 0

    def __call__(self, func):
        if iscoroutinefunction(func):
            @wraps(func)
            async def decorator(*args, **kwargs):
                self.request()
                return await func(*args, **kwargs)
        else:
            @wraps(func)
            def decorator(*args, **kwargs):
                self.request()
                return func(*args, **kwargs)
        return decorator

    @property
    def reset_time(self):
        return round(self._reset_time - time())

    def request(self):
        if self._reset_time == 0 or self._reset_time < time(): # If reset time hasn't be set, or has passed the reset time
            self._reset_time = time() + self.period # Set reset time
            self._requests_in_period = 0 # Reset requests period

        if self._requests_in_period >= self.calls: # If requests are above what they should be
            raise RateLimitExceeded(self.reset_time)
        self._requests_in_period += 1 # Otherwise just iterate requests