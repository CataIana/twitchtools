from typing import TypeVar, Callable
import disnake
from disnake.ext import commands
from .custom_context import ApplicationCustomContext

T = TypeVar("T")


def has_manage_permissions() -> Callable[[T], T]:
    async def predicate(ctx: ApplicationCustomContext) -> bool:
        if not ctx.guild:
            raise commands.NoPrivateMessage

        # Bot owner override all permissions
        if await ctx.bot.is_owner(ctx.author):
            return True

        if ctx.author.guild_permissions.administrator:
            return True

        manager_role_id = await ctx.bot.db.get_manager_role(ctx.guild)
        manager_role = ctx.guild.get_role(manager_role_id)
        if manager_role:
            if manager_role in ctx.author.roles:
                return True

        raise commands.CheckFailure(
            "You do not have permission to run this command. Only server administrators or users with the manager role can run commands. If you believe this is a mistake, ask your admin about the `/managerrole` command")

    return commands.check(predicate)


def has_guild_permissions(owner_override: bool = False, **perms: bool) -> Callable[[T], T]:
    """Similar to :func:`.has_permissions`, but operates on guild wide
    permissions instead of the current channel permissions.

    If this check is called in a DM context, it will raise an
    exception, :exc:`.NoPrivateMessage`.

    .. versionadded:: 1.3

    Modifications: Allows owner override of permissions
    """

    invalid = set(perms) - set(disnake.Permissions.VALID_FLAGS)
    if invalid:
        raise TypeError(f"Invalid permission(s): {', '.join(invalid)}")

    async def predicate(ctx: ApplicationCustomContext) -> bool:
        if not ctx.guild:
            raise commands.NoPrivateMessage

        if owner_override:
            if await ctx.bot.is_owner(ctx.author):
                return True

        permissions = ctx.author.guild_permissions
        missing = [perm for perm, value in perms.items(
        ) if getattr(permissions, perm) != value]

        if not missing:
            return True

        raise commands.MissingPermissions(missing)

    return commands.check(predicate)


def check_channel_permissions(ctx: ApplicationCustomContext, channel: disnake.TextChannel):
    perms = {"view_channel": True,
             "read_message_history": True, "send_messages": True}
    permissions = channel.permissions_for(ctx.guild.me)

    missing = [perm for perm, value in perms.items(
    ) if getattr(permissions, perm) != value]
    if not missing:
        return True

    raise commands.BotMissingPermissions(missing)