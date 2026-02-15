from disnake import ComponentType
from disnake.interactions import (ApplicationCommandInteraction,
                                  MessageInteraction, ModalInteraction)
from disnake.state import ConnectionState

#from .custom_context import ApplicationCustomContext


class CustomConnectionState(ConnectionState):
    def parse_interaction_create(self, data) -> None:
        # The only line changed. Allows us to make any of the interactions our own class, long as we override the recievers
        self.dispatch("raw_interaction", data)
        if data["type"] == 1:
            # PING interaction should never be received
            return

        elif data["type"] == 2:
            interaction = ApplicationCommandInteraction(data=data, state=self)
            self.dispatch("application_command", interaction)

        elif data["type"] == 3:
            interaction = MessageInteraction(data=data, state=self)
            self._view_store.dispatch(interaction)
            self.dispatch("message_interaction", interaction)
            if interaction.data.component_type is ComponentType.button:
                self.dispatch("button_click", interaction)
            elif interaction.data.component_type is ComponentType.select:
                self.dispatch("dropdown", interaction)

        elif data["type"] == 4:
            interaction = ApplicationCommandInteraction(data=data, state=self)
            self.dispatch("application_command_autocomplete", interaction)

        elif data["type"] == 5:
            interaction = ModalInteraction(data=data, state=self)
            self._modal_store.dispatch(interaction)
            self.dispatch("modal_submit", interaction)

        else:
            return

        self.dispatch("interaction", interaction)
