from disnake import ApplicationCommandInteraction
from disnake.utils import snowflake_time
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import TwitchCallBackBot


class ApplicationCustomContext(ApplicationCommandInteraction):
    def __init__(self, *args, **kwargs):
        bot: TwitchCallBackBot = kwargs.pop("bot")
        super().__init__(*args, **kwargs)
        self.bot = bot
        if self.bot.intents.members:
            if self.guild:
                self.author = self.guild.get_member(self.author.id)
            else:
                self.author = self.bot.get_user(self.author.id)
        self.edit = self.edit_original_message

    @property
    def created_at(self):
        return snowflake_time(self.id)