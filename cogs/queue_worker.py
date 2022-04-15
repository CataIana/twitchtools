from disnake.ext import commands
from twitchtools import TitleEvent, Stream, User, PartialUser
import asyncio
from typing import TYPE_CHECKING, Union
if TYPE_CHECKING:
    from main import TwitchCallBackBot

class QueueWorker(commands.Cog):
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()
        self.worker = self.bot.loop.create_task(self._worker())
        self.status_cog = self.bot.get_cog("StreamStatus")

    def cog_unload(self):
        self.worker.cancel()

    async def _worker(self):
        self.bot.log.debug("Queue Worker Started")
        while not self.bot.is_closed():
            item: Union[Stream, User, TitleEvent] = await self.bot.queue.get()
            self.bot.log.debug(f"Recieved event! {type(item).__name__}")
            if self.status_cog is None:
                self.status_cog = self.bot.get_cog("StreamStatus")
                if self.status_cog is None:
                    self.bot.log.critical("Unable to find status cog to dispatch events!")
                    self.bot.queue.task_done()
            if isinstance(item, Stream): # Stream online
                if self.status_cog:
                    #await self.status_cog.on_streamer_online(item)
                    try:
                        await asyncio.wait_for(self.status_cog.on_streamer_online(item), timeout=10)
                    except asyncio.TimeoutError:
                        pass
                self.bot.dispatch("streamer_online", item)

            elif isinstance(item, (User, PartialUser)): # Stream offline
                if self.status_cog:
                    #await self.status_cog.on_streamer_offline(item)
                    try:
                        await asyncio.wait_for(self.status_cog.on_streamer_offline(item), timeout=10)
                    except asyncio.TimeoutError:
                        pass
                self.bot.dispatch("streamer_offline", item)

            elif isinstance(item, TitleEvent): # Title Change
                if self.status_cog:
                    #await self.status_cog.on_title_change(item)
                    try:
                        await asyncio.wait_for(self.status_cog.on_title_change(item), timeout=10)
                    except asyncio.TimeoutError:
                        pass
                self.bot.dispatch("title_change", item)

            else:
                self.bot.log.warn(f"Recieved bad queue object with type \"{type(item).__name__}\"!")

            self.bot.log.debug(f"Finished task {type(item).__name__}")
            self.bot.queue.task_done()


def setup(bot):
    bot.add_cog(QueueWorker(bot))
