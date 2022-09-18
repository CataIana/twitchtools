from asyncio import iscoroutinefunction
from typing import Callable, List, Optional, Union

from disnake import ButtonStyle, Emoji, Forbidden, NotFound, PartialEmoji, ui
from disnake.interactions import MessageInteraction
from disnake.ui import Button, View

from .custom_context import ApplicationCustomContext


class ButtonCallback(Button):
    def __init__(
        self,
        *,
        style: ButtonStyle = ButtonStyle.secondary,
        label: Optional[str] = None,
        disabled: bool = False,
        custom_id: Optional[str] = None,
        callback: Optional[Callable] = None,
        url: Optional[str] = None,
        emoji: Optional[Union[str, Emoji, PartialEmoji]] = None,
        row: Optional[int] = None,
    ):
        super().__init__(style=style, label=label, disabled=disabled,
                         custom_id=custom_id, url=url, emoji=emoji, row=row)
        if not iscoroutinefunction(callback):
            raise TypeError("Callback must be a coroutine!")
        self.callback = callback

class Confirm(View):
    def __init__(self, ctx: ApplicationCustomContext):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.bot = ctx.bot
        self.value: Optional[bool] = None
        self.children: list[Button]
        self.interaction: MessageInteraction

    async def interaction_check(self, interaction: MessageInteraction) -> bool:
        if not interaction.author == self.ctx.author:
            await interaction.send("You're not the author!", ephemeral=True)
            return False
        return True

    @ui.button(label="Confirm", style=ButtonStyle.green)
    async def confirm(self, button: Button, interaction: MessageInteraction):
        self.value = True
        self.interaction = interaction
        self.stop()

    @ui.button(label="Cancel", style=ButtonStyle.grey)
    async def cancel(self, button: Button, interaction: MessageInteraction):
        self.value = False
        self.interaction = interaction
        self.stop()

class TextPaginator(View):
    def __init__(self, ctx: ApplicationCustomContext, pages: List[str], show_delete: bool = False):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.pages = pages
        self.page_no: int = 1        
        if show_delete:
            self.add_item(ButtonCallback(style=ButtonStyle.blurple, emoji="🗑️", callback=self.delete))
        self.update_button_state()

    def update_button_state(self):
        self.children[0].disabled = True if self.page_no == 1 else False
        self.children[1].disabled = True if self.page_no == len(self.pages) else False

    async def delete(self, interaction: MessageInteraction):
        try:
            await interaction.message.delete()
        except NotFound:
            pass
        try:
            await self.ctx.message.delete()
        except AttributeError:
            pass
        except NotFound:
            pass
        except Forbidden:
            pass

    async def interaction_check(self, interaction: MessageInteraction) -> bool:
        if not interaction.author == self.ctx.author:
            await interaction.send("You're not the author!", ephemeral=True)
            return False
        return True

    @ui.button(label="Previous page", style=ButtonStyle.red, disabled=True)
    async def back(self, button: ui.Button, interaction: MessageInteraction):
        self.page_no -= 1
        self.update_button_state()
        await interaction.response.edit_message(content=self.pages[self.page_no-1], view=self)

    @ui.button(label="Next page", style=ButtonStyle.green)
    async def forward(self, button: ui.Button, interaction: MessageInteraction):
        self.page_no += 1
        self.update_button_state()
        await interaction.response.edit_message(content=self.pages[self.page_no-1], view=self)