from dislash import InteractionClient, SlashInteraction, BaseInteraction, ContextMenuInteraction, MessageInteraction, ComponentType
from dislash.application_commands._decohub import _HANDLER
from typing import Union

class CustomSlashInteraction(SlashInteraction):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.client.intents.members:
            if self.guild:
                self.author = self.guild.get_member(self.author.id)
            else:
                self.author = self.bot.get_user(self.author.id)

    async def reinvoke(self):
        try:
            await self.slash_command._maybe_cog_call(self.slash_command._cog, self, self.data)
            await self.slash_command.invoke_children(self)
        except Exception as err:
            self.slash_command._dispatch_error(self.slash_command._cog, self, err)
            raise err

class CustomContextMenuInteraction(ContextMenuInteraction):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.client.intents.members:
            if self.guild:
                self.author = self.guild.get_member(self.author.id)
            else:
                self.author = self.bot.get_user(self.author.id)

    async def reinvoke(self):
        return

class CustomMessageInteraction(MessageInteraction):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.client.intents.members:
            if self.guild:
                self.author = self.guild.get_member(self.author.id)
            else:
                self.author = self.bot.get_user(self.author.id)

    async def reinvoke(self):
        return


class CustomInteractionClient(InteractionClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def invoke(self, inter: Union[CustomSlashInteraction, CustomMessageInteraction, CustomContextMenuInteraction]):
        if isinstance(inter, CustomSlashInteraction):
            self.client.dispatch('slash_command', inter)
            await self._on_slash_command(inter)
        elif isinstance(inter, CustomContextMenuInteraction):
            if inter.data.type == 2:
                self.client.dispatch('user_command', inter)
            elif inter.data.type == 3:
                self.client.dispatch('message_command', inter)
            await self._on_user_command(inter)
        elif isinstance(inter, CustomMessageInteraction):
            self.client.dispatch("message_interaction", inter)
            if inter.component is None:
                return
            if inter.component.type == ComponentType.Button:
                self.client.dispatch('button_click', inter)
            elif inter.component.type == ComponentType.SelectMenu:
                self.client.dispatch('dropdown', inter)
            await self._on_message_command(inter)

    async def get_context(self, payload, cls = None):
        if cls:
            return cls(self.client, payload)
        else:
            _type = payload.get("type", 1)
            if _type == 2:
                data_type = payload.get("data", {}).get("type", 1)
                if data_type == 1:
                    return CustomSlashInteraction(self.client, payload)
                elif data_type in (2, 3):
                    return CustomContextMenuInteraction(self.client, payload)
            elif _type == 3:
                return CustomMessageInteraction(self.client, payload)

    async def _on_slash_command(self, inter: SlashInteraction):
        app_command = self.slash_commands.get(inter.data.name)
        if app_command is None:
            usable = False
        else:
            guild_ids = app_command.guild_ids or self._test_guilds
            is_global = self.get_global_command(inter.data.id) is not None 
            if guild_ids is None:
                usable = is_global
            else:
                usable = not is_global and inter.guild_id in guild_ids
        if usable:
            try:
                await app_command.invoke(inter)
            except Exception as err:
                await self._activate_event('slash_command_error', inter, err)
            else:
                await self._activate_event('slash_command_completion', inter)
        else:
            await self._maybe_unregister_commands(inter.guild_id)

    async def _on_user_command(self, inter: ContextMenuInteraction):
        app_command = _HANDLER.user_commands.get(inter.data.name)
        if app_command is None:
            usable = False
        else:
            guild_ids = app_command.guild_ids or self._test_guilds
            is_global = self.get_global_command(inter.data.id) is not None 
            if guild_ids is None:
                usable = is_global
            else:
                usable = not is_global and inter.guild_id in guild_ids
        if usable:
            try:
                await app_command.invoke(inter)
            except Exception as err:
                await self._activate_event('user_command_error', inter, err)
            else:
                await self._activate_event('user_command_completion', inter)
        else:
            await self._maybe_unregister_commands(inter.guild_id)
    
    async def _on_message_command(self, inter: ContextMenuInteraction):
        app_command = _HANDLER.message_commands.get(inter.data.name)
        if app_command is None:
            usable = False
        else:
            guild_ids = app_command.guild_ids or self._test_guilds
            is_global = self.get_global_command(inter.data.id) is not None 
            if guild_ids is None:
                usable = is_global
            else:
                usable = not is_global and inter.guild_id in guild_ids
        if usable:
            try:
                await app_command.invoke(inter)
            except Exception as err:
                await self._activate_event('message_command_error', inter, err)
            else:
                await self._activate_event('message_command_completion', inter)
        else:
            await self._maybe_unregister_commands(inter.guild_id)

    async def _process_interaction(self, payload):
        event_name = "dislash_interaction" if self._uses_discord_2 else "interaction"
        _type = payload.get("type", 1)
        # Received a ping
        if _type == 1:
            inter = BaseInteraction(self.client, payload)
            # Meh, why call the event for a ping
            #self.dispatch(event_name, inter)
            return await inter.create_response(type=1)
        self.dispatch(event_name, payload)
        # Application command invoked
        #elif _type == 2:
            #data_type = payload.get("data", {}).get("type", 1)
            #if data_type == 1:
                #inter = SlashInteraction(self.client, payload)
                #self.dispatch(event_name, payload)
                # self.dispatch('slash_command', inter)
                #await self._on_slash_command(inter)
            #elif data_type in (2, 3):
                # inter = ContextMenuInteraction(self.client, payload)
                #self.dispatch(event_name, payload)
                # if data_type == 2:
                #     self.dispatch('user_command', inter)
                #     await self._on_user_command(inter)
                # elif data_type == 3:
                #     self.dispatch('message_command', inter)
                #     await self._on_message_command(inter)
        # Message component clicked
        #elif _type == 3:
            #inter = MessageInteraction(self.client, payload)
            #self.dispatch(event_name, payload)
            #self.dispatch("message_interaction", inter)
            # if inter.component is None:
            #     return
            # if inter.component.type == ComponentType.Button:
            #     self.dispatch('button_click', inter)
            # elif inter.component.type == ComponentType.SelectMenu:
            #     self.dispatch('dropdown', inter)

    #ctx = await self.bot.get_context(message, cls=CustomContext)
    #await self.bot.invoke(ctx)