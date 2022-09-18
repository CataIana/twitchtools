from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List

from disnake import ApplicationCommand, Client, SyncWarning
from disnake.ext.commands.interaction_bot_base import _app_commands_diff

if TYPE_CHECKING:
    from twitchtools import TwitchCallBackBot

def _show_diff(self, diff: Dict[str, List[ApplicationCommand]]) -> None:
    if TYPE_CHECKING:
        self: TwitchCallBackBot = self
    to_upsert = f", ".join(cmd.name for cmd in diff["upsert"]) or None
    to_edit = f", ".join(cmd.name for cmd in diff["edit"]) or None
    to_delete = f", ".join(cmd.name for cmd in diff["delete"]) or None
    #no_changes = f", ".join(cmd.name for cmd in diff["no_changes"]) or None
    if to_upsert:
        self.log.info(f"Application Commands To Upsert: {to_upsert}")
    if to_edit:
        self.log.info(f"Application Commands To Edit: {to_edit}")
    if to_delete:
        self.log.info(f"Application Commands To Delete: {to_delete}")
    if not to_upsert and not to_edit and not to_delete:
        self.log.info("No changes to make")

async def _sync_application_commands(self) -> None:
    if TYPE_CHECKING:
        self: TwitchCallBackBot = self
    if not isinstance(self, Client):
        raise NotImplementedError(f"This method is only usable in disnake.Client subclasses")

    if not self._sync_commands or self._is_closed or self.loop.is_closed():
        return

    # We assume that all commands are already cached.
    # Sort all invokable commands between guild IDs:
    global_cmds, guild_cmds = self._ordered_unsynced_commands(self._test_guilds)
    if global_cmds is None:
        return

    # Update global commands first
    diff = _app_commands_diff(
        global_cmds, self._connection._global_application_commands.values()
    )
    update_required = bool(diff["upsert"]) or bool(diff["edit"]) or bool(diff["delete"])

    if self._sync_commands_debug:
        if update_required:
            self.log.info("Updating application commands")
            _show_diff(self, diff)

    if update_required:
        # Notice that we don't do any API requests if there're no changes.
        try:
            to_send = diff["no_changes"] + diff["edit"] + diff["upsert"]
            await self.bulk_overwrite_global_commands(to_send)
        except Exception as e:
            self.log.warn(f"Global command override failed due to {e}", SyncWarning)
    # Same process but for each specified guild individually.
    # Notice that we're not doing this for every single guild for optimisation purposes.
    # See the note in :meth:`_cache_application_commands` about guild app commands.
    for guild_id, cmds in guild_cmds.items():
        current_guild_cmds = self._connection._guild_application_commands.get(guild_id, {})
        diff = _app_commands_diff(cmds, current_guild_cmds.values())
        update_required = bool(diff["upsert"]) or bool(diff["edit"]) or bool(diff["delete"])
        # Show diff
        if self._sync_commands_debug:
            if update_required:
                self.log.info(f"Updating application commands in {self.get_guild(int(guild_id))}")
                _show_diff(self, diff)
        # Do API requests and cache
        if update_required:
            try:
                to_send = diff["no_changes"] + diff["edit"] + diff["upsert"]
                await self.bulk_overwrite_guild_commands(guild_id, to_send)
            except Exception as e:
                self.log.warn(f"Failed to overwrite commands in <Guild id={guild_id}> due to {e}", SyncWarning)
    # Last debug message
    if self._sync_commands_debug:
        self.log.info("Application Command Sync Completed")