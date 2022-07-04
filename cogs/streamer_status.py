import disnake
from disnake.ext import commands
from disnake.utils import utcnow
from twitchtools import Stream, TitleEvent, User, PartialUser, AlertOrigin, human_timedelta, Ratelimit, RateLimitExceeded
from twitchtools.files import get_title_callbacks, get_callbacks, get_title_cache, write_title_cache, get_channel_cache, write_channel_cache
from time import time
from typing import Union
from datetime import timedelta

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import TwitchCallBackBot

class StreamStatus(commands.Cog):
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()
        self.ratelimits: dict[str, Ratelimit] = {}
        self.ignore_cooldowns: bool = False # Used for debugging/development

    async def on_title_change(self, event: TitleEvent):
        await self.bot.wait_until_ready()
        title_callbacks = await get_title_callbacks()
        title_cache = await get_title_cache()
        old_title = title_cache.get(event.broadcaster.username, {}).get("cached_title", "<no title>") #Get cached information for streamer, or none
        old_game = title_cache.get(event.broadcaster.username, {}).get("cached_game", "<no game>")

        updated = [] #Quick way to make the dynamic embed title
        if event.title != old_title:
            updated.append("title")
        if event.game != old_game:
            updated.append("game")

        if updated == []: #If for some reason neither the title or game updated, just ignore
            self.bot.log.info(f"No title updates for {event.broadcaster.username}, ignoring")
            return

        title_cache[event.broadcaster.username] = { #Update cached data
            "cached_title": event.title,
            "cached_game": event.game,
        }

        await write_title_cache(title_cache)

        stream = await self.bot.api.get_stream(event.broadcaster.username, origin=AlertOrigin.callback)
        if stream:
            #self.bot.log.info(f"{event.broadcaster.username} is live, ignoring title change")
            if self.ratelimits.get(event.broadcaster.username, None) is None:
                self.ratelimits[event.broadcaster.username] = Ratelimit(calls=10, period=600)
            try:
                self.ratelimits[event.broadcaster.username].request()
            except RateLimitExceeded:
                self.bot.log.info(f"Title update ratelimit for {event.broadcaster.username} exceeded!")
                return
            channel_cache = await get_channel_cache()
            stream.user = await self.bot.api.get_user(user=stream.user)
            embed = disnake.Embed(
                title=event.title, url=f"https://twitch.tv/{event.broadcaster.username}",
                description=f"Streaming {event.game}\n[Watch Stream](https://twitch.tv/{event.broadcaster.name})",
                colour=8465372, timestamp=stream.started_at)
            embed.set_author(name=f"{event.broadcaster.display_name} is now live on Twitch!", url=f"https://twitch.tv/{event.broadcaster.username}", icon_url=stream.user.avatar)
            embed.set_footer(text="Mew")
            # Add new game to games list if applicable
            if "games" in channel_cache.get(event.broadcaster.username, {}).keys() and event.game != old_game:
                old_time = channel_cache[event.broadcaster.username]["games"].get(event.game_name, 0)
                if event.game_name in channel_cache[event.broadcaster.username]["games"].keys():
                    channel_cache[event.broadcaster.username]["games"].pop(event.game_name, None)
                if channel_cache[event.broadcaster.username]["games"].get(old_game, None) != None:
                    channel_cache[event.broadcaster.username]["games"][old_game] = (int(time()) - channel_cache[event.broadcaster.username]["last_update"]) + old_time
                channel_cache[event.broadcaster.username]["games"][event.game_name] = old_time
                channel_cache[event.broadcaster.username]["last_update"] = int(time())
                await write_channel_cache(channel_cache)
            for m in channel_cache.get(event.broadcaster.username, {}).get("live_alerts", []):
                channel = self.bot.get_channel(m.get("channel", None))
                if channel:
                    try:
                        message = await channel.fetch_message(m.get("message", None))
                        await message.edit(embed=embed)
                    except disnake.NotFound:
                        pass
                    except disnake.Forbidden:
                        pass
            return

        if title_callbacks.get(event.broadcaster.username, None) is None:
            return

        user = await self.bot.api.get_user(user_id=event.broadcaster.id)
        #Create embed for discord
        embed = disnake.Embed(url=f"https://twitch.tv/{event.broadcaster.username}", colour=0x812BDC, timestamp=utcnow())
        if event.title != old_title:
            embed.add_field(name="Old Title", value=old_title, inline=True)
            embed.add_field(name="New Title", value=event.title, inline=True)
        if event.game != old_game:
            embed.add_field(name="Old Game", value=old_game, inline=True)
            embed.add_field(name="New Game", value=event.game, inline=True)
        embed.set_author(name=f"{event.broadcaster.display_name} updated their {' and '.join(updated)}!", url=f"https://twitch.tv/{event.broadcaster.username}", icon_url=user.avatar)
        embed.set_footer(text="Mew")

        self.bot.log.info(f"Sending title update for {event.broadcaster.username}")

        #Send embed to each defined channel
        for data in title_callbacks[event.broadcaster.username]["alert_roles"].values():
            c = self.bot.get_channel(data["notif_channel_id"])
            if c is not None:
                if data['role_id'] is None:
                    role_mention = ""
                elif data["role_id"] == "everyone":
                    role_mention = "@everyone"
                else:
                    role_mention = f"<@&{data['role_id']}>"
                try:
                    await c.send(f"{role_mention}", embed=embed)
                except disnake.Forbidden:
                    pass
                except disnake.HTTPException:
                    pass

    async def on_streamer_offline(self, streamer: Union[User, PartialUser]):
        await self.bot.wait_until_ready()
        channel_cache = await get_channel_cache()
        callbacks = await get_callbacks()
        if not callbacks:
            return
        # Check if there's anything to even be done, if not, just return
        if channel_cache.get(streamer.username, {}).get("live_channels", None) is None and channel_cache.get(streamer.username, {}).get("live_alerts", None) is None:
            return
        self.bot.log.info(f"Updating status to offline for {streamer}")

        # Iterate through all live channels, if applicable, either deleting them or renaming them to stream-offline depending on mode
        for channel_id in channel_cache[streamer.username].get("live_channels", []):
            channel = self.bot.get_channel(channel_id)
            if channel is not None:
                try:
                    if callbacks[streamer.username]["alert_roles"][str(channel.guild.id)]["mode"] == 0:
                        await channel.delete()
                    elif callbacks[streamer.username]["alert_roles"][str(channel.guild.id)]["mode"] == 2:
                        await channel.edit(name="stream-offline")
                except disnake.Forbidden:
                    continue
                except disnake.HTTPException:
                    continue

        
        # Delete live channel data after being used
        channel_cache[streamer.username].pop("live_channels", None)
        
        # Just like channels, iterate through the sent live alerts, and make them past tense. 100% suseptible to edge cases
        for alert_ids in channel_cache[streamer.username].get("live_alerts", []):
            channel = self.bot.get_channel(alert_ids["channel"])
            if channel is not None:
                try: #Try to get the live alerts message, skipping if not found
                    message = await channel.fetch_message(alert_ids["message"]) 
                except disnake.NotFound:
                    continue
                else:
                    try: #Get the live alert embed, skipping it was removed, or something else happened
                        embed = message.embeds[0]
                    except IndexError:
                        continue
                    else:
                        try: #Replace the applicable strings with past tense phrasing
                            embed.set_author(name=f"{streamer.display_name} is now offline", url=embed.author.url, icon_url=embed.author.icon_url)
                            #embed.set_author(name=embed.author.name.replace("is now live on Twitch!", "was live on Twitch!"), url=embed.author.url)
                            extracted_game = embed.description.split('Streaming ', 1)[1].split('\n')[0]
                            if "games" in channel_cache[streamer.username]:
                                games = channel_cache[streamer.username]["games"] # Limit to last 5 games
                                if len(games) == 1:
                                    past_games = f"Was streaming {extracted_game} for ~{human_timedelta(utcnow(), source=embed.timestamp, accuracy=2)}"
                                else:
                                    sliced_games = {key: games[key] for key in list(games.keys())[:5]}
                                    sliced_games[list(sliced_games.keys())[-1]] += int(time()) - channel_cache[streamer.username]["last_update"]
                                    past_games = []
                                    for game_name, length in sliced_games.items():
                                        if length == 0:
                                            continue
                                        past_games.append(f"{game_name} for ~{human_timedelta(embed.timestamp+timedelta(seconds=length), source=embed.timestamp, accuracy=2)}")
                                    extra = " (5 most recent)" if len(games) > 5 else ""
                                    past_games = f"Was streaming{extra}:" + "\n" + ',\n'.join(past_games)
                            else:
                                #Fallback
                                self.bot.log.warning("Using fallback game extraction")
                                past_games = f"Was streaming {extracted_game} for ~{human_timedelta(utcnow(), source=embed.timestamp, accuracy=2)}"
                            embed.description = past_games
                            try:
                                await message.edit(content=f"{streamer.display_name} is now offline", embed=embed)
                                #await message.edit(content=message.content.replace("is live on Twitch!", "was live on Twitch!"), embed=embed)
                            except disnake.Forbidden: #In case something weird happens
                                continue
                        except IndexError: #In case something weird happens when parsing the embed values
                            self.bot.log.warning(f"Error editing message to offline in {channel.guild.name}")
        
        # Remove data once used
        if channel_cache[streamer.username].get("live_alerts", []) != []:
            channel_cache[streamer.username]["reusable_alerts"] = channel_cache[streamer.username]["live_alerts"]
        channel_cache[streamer.username].pop("live_alerts", None)
        channel_cache[streamer.username]["is_live"] = False
        channel_cache[streamer.username].pop("games", None)
        channel_cache[streamer.username].pop("last_update", None)

        # Update cache
        await write_channel_cache(channel_cache)

    def on_cooldown(self, alert_cooldown: int) -> bool:
        if int(time()) - alert_cooldown < 600 and not self.ignore_cooldowns:
            return True
        return False

    def is_live(self, channel_cache: dict, stream: Stream):
        # To reduce the likelyhood of strange errors, clarify this.
        if channel_cache.get(stream.user.username, {}).get("is_live", False):
            return True
        # c = dict(channel_cache.get(stream.user.username, {}))
        # try:
        #     del c["alert_cooldown"]
        # except KeyError:
        #     pass
        # if c == {}:
        #     return False
        # return True

    async def on_streamer_online(self, stream: Stream):
        await self.bot.wait_until_ready()
        channel_cache = await get_channel_cache()
        callbacks = await get_callbacks()
        on_cooldown = self.on_cooldown(channel_cache.get(stream.user.username, {}).get("alert_cooldown", 0))

        # Do not re-run this function is the streamer is already live
        if self.is_live(channel_cache, stream):
            if stream.origin == AlertOrigin.callback:
                self.bot.log.info(f"Ignoring alert while live for {stream.user.username}")
            return

        if on_cooldown: # There is a 10 minute cooldown between alerts, but live channels will still be created
            self.bot.log.info(f"Cooldown active for {stream.user.username}, updating/recreating channels and restoring notification messages")

        self.bot.log.info(f"Updating status to online for {stream.user.username}")

        # Sending webhook if applicable
        await self.do_webhook(callbacks, stream)
        
        # Create embed message
        stream.user = await self.bot.api.get_user(user=stream.user)
        embed = disnake.Embed(
            title=stream.title, url=f"https://twitch.tv/{stream.user.name}",
            description=f"Streaming {stream.game}\n[Watch Stream](https://twitch.tv/{stream.user.name})",
            colour=8465372, timestamp=stream.started_at)
        embed.set_author(name=f"{stream.user.display_name} is now live on Twitch!", url=f"https://twitch.tv/{stream.user.name}", icon_url=stream.user.avatar)
        embed.set_footer(text="Mew")

        #Permission overrides
        SelfOverride = disnake.PermissionOverwrite() # Make sure the bot has permission to access the channel
        SelfOverride.view_channel = True
        SelfOverride.send_messages = True
        DefaultRole = disnake.PermissionOverwrite() # Deny @everyone access
        DefaultRole.view_channel = False
        DefaultRole.send_messages = False
        OverrideRole = disnake.PermissionOverwrite() # Give users with the role access to view only
        OverrideRole.view_channel = True

        live_channels = []
        live_alerts = []
        reuse_done = False
        for guild_id, alert_info in callbacks[stream.user.username]["alert_roles"].items():
            guild = self.bot.get_guild(int(guild_id))
            if guild is None:
                continue

            #Format role mention
            if alert_info["role_id"] == "everyone":
                role_mention = f" {guild.default_role}"
            elif alert_info["role_id"] == None:
                role_mention = ""
            else:
                role = guild.get_role(alert_info["role_id"])
                role_mention = f" {role.mention}"


            if not on_cooldown: # Send live alert if not on alert cooldown, and append channel id and message id to channel cache
                alert_channel_id = alert_info.get("notif_channel_id", None)
                alert_channel = self.bot.get_channel(alert_channel_id)
                if alert_channel is not None:
                    try:
                        user_escaped = stream.user.display_name.replace('_', '\_')
                        live_alert = await alert_channel.send(alert_info.get("custom_message", f"{user_escaped} is live on Twitch!")+role_mention, embed=embed)
                        live_alerts.append({"channel": live_alert.channel.id, "message": live_alert.id})
                    except disnake.Forbidden:
                        pass
                    except disnake.HTTPException:
                        pass
            elif not reuse_done:
                self.bot.log.debug("Running alert reuse")
                if channel_cache[stream.user.username].get("reusable_alerts", None) is not None:
                    for alert in channel_cache[stream.user.username]["reusable_alerts"]:
                        alert_channel_id = alert.get("channel", None)
                        alert_channel = self.bot.get_channel(alert_channel_id)
                        if alert_channel is not None:
                            try:
                                alert_message = await alert_channel.fetch_message(alert.get("message"))
                            except disnake.NotFound:
                                pass
                            else:
                                try:
                                    user_escaped = stream.user.display_name.replace('_', '\_')
                                    live_alert = await alert_message.edit(content=alert_info.get("custom_message", f"{user_escaped} is live on Twitch!")+role_mention, embed=embed)
                                    live_alerts.append({"channel": live_alert.channel.id, "message": live_alert.id})
                                except disnake.Forbidden:
                                    pass
                                except disnake.HTTPException:
                                    pass
                reuse_done = True # Since reuse is all done in the first iteration, don't waste time doing it again

            if alert_info["mode"] == 0: # Temporary live channel mode

                # Create channel overrides
                NewChannelOverrides = {self.bot.user: SelfOverride}
                if alert_info["role_id"] != "everyone":
                    NewChannelOverrides[guild.default_role] = DefaultRole
                if alert_info["role_id"] is not None and alert_info["role_id"] != "everyone":
                    NewChannelOverrides[role] = OverrideRole

                # Check if channel doesn't already exist. Kind of a bad idea, but does effectively prevent duplicate channels
                #if f"🔴{stream.user.username}" not in [channel.name for channel in guild.text_channels]:
                    # Create temporary channel and add channel id to channel cache
                try:
                    channel = await guild.create_text_channel(f"🔴{stream.user.username}", overwrites=NewChannelOverrides, position=0)
                    if channel:
                        user_escaped = stream.user.display_name.replace('_', '\_')
                        await channel.send(f"{user_escaped} is live! https://twitch.tv/{stream.user.name}")
                        live_channels.append(channel.id)
                except disnake.Forbidden:
                    self.bot.log.warning(f"Permission error creating text channels in guild {guild.name}! ({stream.user.username})")

            elif alert_info["mode"] == 1: # Notification is already sent, nothing needed to be done
                pass
            
            # Permanent channel. Do the same as above, but modify the existing channel, instead of making a new one
            elif alert_info["mode"] == 2:
                channel = self.bot.get_channel(alert_info["channel_id"])
                if channel is not None:
                    try:
                        await channel.edit(name="🔴now-live")
                        live_channels.append(channel.id)
                    except disnake.Forbidden:
                        self.bot.log.warning(f"Forbidden error updating {stream.user.username} in guild {channel.guild.name}")
                else:
                    self.bot.log.warning(f"Error fetching channel ID {alert_info['channel_id']} for {stream.user.username}1")
        
        #Finally, combine all data into channel cache, and update the file
        channel_cache[stream.user.username] = {"alert_cooldown": int(time()), "is_live": True, "live_channels": live_channels, "live_alerts": live_alerts, "last_update": int(time()), "games": {stream.game_name: 0}}

        await write_channel_cache(channel_cache)

    async def do_webhook(self, callbacks: dict, stream: Stream):
        if "webhook" in callbacks[stream.user.username].keys():
            if "format" in callbacks[stream.user.username].keys():
                format_ = callbacks[stream.user.username]["format"].format(stream).replace("\\n", "\n")
            else:
                format_ = f"{stream.user.display_name} is live! Streaming {stream.game}!\nhttps://twitch.tv/{stream.user.username}"
            if type(callbacks[stream.user.username]["webhook"]) == list:
                webhooks = callbacks[stream.user.username]["webhook"]
            else:
                webhooks = [callbacks[stream.user.username]["webhook"]]
            for webhook in webhooks:
                webhook_obj = disnake.Webhook.from_url(webhook, session=self.bot.aSession)
                try:
                    await webhook_obj.send(content=format_)
                except disnake.NotFound:
                    pass

def setup(bot):
    bot.add_cog(StreamStatus(bot))
