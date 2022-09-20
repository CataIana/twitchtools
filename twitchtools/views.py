from asyncio import iscoroutinefunction
from pydoc import render_doc
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


class SortableTextPaginator(View):
    def __init__(self, ctx: ApplicationCustomContext, data: dict, page_generator: Callable, sorting_options: dict[str, bool], show_delete: bool = False):
        """A sortable text paginator that generates pages on the go. Requires a function that generates pages from some data, the available sorting keys, and the data to be used

        Parameters
        ----------
        ctx: :class:`ApplicationCustomContext`
            Context
        data: :class:`dict`
            A dictionary containing the data to be parsed
        page_generator: :class:`Callable`
            A synchronous function that is called to generate pages. Must return `list[str]`
        sorting_options: :class:`dict[str, bool]`
            A dictionary containing available options to sort. The key should be the sortable key, and the value is whether to invert the sort
        show_delete: :class:`bool`
            Whether to show a delete button or not
        """
        super().__init__(timeout=None)
        self.ctx = ctx
        self._data = data

        self._page_generator = page_generator
        self.sorting_options = sorting_options
        if not isinstance(sorting_options, dict):
            raise TypeError("Sortable options must be a dictionary!")
        if sorting_options == {}:
            raise TypeError("Sortable options cannot be empty!")

        self.sort_by_index = 0
        self.page_no: int = 1
        self.pages: list[str] = self.render_pages()
        self.add_item(ButtonCallback(custom_id="sort_button", style=ButtonStyle.blurple,
                      label=f"Sort by: {list(self.sorting_options.keys())[self.sort_by_index].replace('_', ' ').title()}", callback=self.update_sort))
        if show_delete:
            self.add_item(ButtonCallback(style=ButtonStyle.blurple,
                          emoji="🗑️", callback=self.delete))
        self.render_pages()
        self.update_button_state()

    def render_pages(self):
        self.pages = self._page_generator(
            self._data, list(self.sorting_options.keys())[self.sort_by_index], list(self.sorting_options.values())[self.sort_by_index])

    def update_button_state(self):
        self.children[0].disabled = True if self.page_no == 1 else False
        self.children[1].disabled = True if self.page_no == len(
            self.pages) else False

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

    async def update_sort(self, interaction: MessageInteraction):
        self.sort_by_index += 1
        if len(self.sorting_options) == self.sort_by_index:
            self.sort_by_index = 0
        self.render_pages()
        self.page_no = 1
        for children in self.children:
            if children.custom_id == "sort_button":
                children.label = f"Sort by: {list(self.sorting_options.keys())[self.sort_by_index].replace('_', ' ').capitalize()}"
        self.update_button_state()
        await interaction.response.edit_message(content=self.pages[self.page_no-1], view=self)

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
