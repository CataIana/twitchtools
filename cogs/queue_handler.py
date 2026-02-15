import asyncio
from traceback import format_exc, format_exception
from typing import TYPE_CHECKING, Union

from disnake.ext import commands

from twitchtools import (PartialUser, PartialYoutubeUser, Stream, TitleEvent,
                         User, YoutubeUser, YoutubeVideo)

if TYPE_CHECKING:
    from main import TwitchCallBackBot

    from .state_manager import StreamStateManager


class QueueHandler(commands.Cog):
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()
        # NEVER ASSIGN A TASK TO A VARIABLE AGAIN MYAAA.
        # Caused a bug that would cause this worker to get stuck with no errors
        self.bot.loop.create_task(self.ensure_queue())
        self.status_cog: StreamStateManager = self.bot.get_cog("StreamStateManager")

    async def ensure_queue(self):
        while True:
            self.queue_task = self.bot.loop.create_task(self.queue_handler())
            try:
                await asyncio.gather(self.queue_task, return_exceptions=False)
            except Exception as e:
                exc = ''.join(format_exception(type(e), e, e.__traceback__))
                self.bot.log.error(f"Queue ran into an exception:\n{exc}")

    async def queue_handler(self):
        self.bot.log.debug("Queue Worker Started")
        while not self.bot.is_closed():
            item: Union[Stream, User, PartialUser, TitleEvent, YoutubeVideo, YoutubeUser, PartialYoutubeUser] = await self.bot.queue.get()
            if isinstance(item, (Stream, YoutubeVideo)):
                self.bot.log.debug(f"Recieved task with type {type(item).__name__} for {item.user.display_name}")
            elif isinstance(item, (User, PartialUser, YoutubeUser, PartialYoutubeUser)):
                self.bot.log.debug(f"Recieved task with type {type(item).__name__} for {item.display_name}")    
            elif isinstance(item, TitleEvent):
                self.bot.log.debug(f"Recieved task with type {type(item).__name__} for {item.broadcaster.display_name}")
            else:
                self.bot.log.debug(f"Recieved task with type {type(item).__name__}")
            if self.status_cog is None:
                self.status_cog = self.bot.get_cog("StreamStatus")
                if self.status_cog is None:
                    self.bot.log.critical(
                        "Unable to find status cog to dispatch events!")
                    self.bot.queue.task_done()
            if isinstance(item, Stream):  # Stream online
                if self.status_cog:
                    await self.status_cog.on_streamer_online(item)
                self.bot.dispatch("streamer_online", item)

            elif isinstance(item, (User, PartialUser)):  # Stream offline
                if self.status_cog:
                    await self.status_cog.on_streamer_offline(item)
                self.bot.dispatch("streamer_offline", item)

            elif isinstance(item, TitleEvent):  # Title Change
                if self.status_cog:
                    await self.status_cog.on_title_change(item)
                self.bot.dispatch("title_change", item)
            
            elif isinstance(item, YoutubeVideo):
                if self.status_cog:
                    await self.status_cog.on_youtube_streamer_online(item)
                self.bot.dispatch("youtube_streamer_online", item)

            elif isinstance(item, (YoutubeUser, PartialYoutubeUser)):
                if self.status_cog:
                    await self.status_cog.on_youtube_streamer_offline(item)
                self.bot.dispatch("youtube_streamer_offline", item)

            else:
                self.bot.log.warning(
                    f"Recieved bad queue object with type \"{type(item).__name__}\"!")

            if isinstance(item, (Stream, YoutubeVideo)):
                self.bot.log.debug(f"Finished task with type {type(item).__name__} for {item.user.display_name}")
            elif isinstance(item, (User, PartialUser, YoutubeUser, PartialYoutubeUser)):
                self.bot.log.debug(f"Finished task with type {type(item).__name__} for {item.display_name}")    
            elif isinstance(item, TitleEvent):
                self.bot.log.debug(f"Finished task with type {type(item).__name__} for {item.broadcaster.display_name}")
            else:
                self.bot.log.debug(f"Finished task with type {type(item).__name__}")
            self.bot.queue.task_done()


def setup(bot):
    bot.add_cog(QueueHandler(bot))
