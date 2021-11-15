import discord
from discord.ext import commands
from discord.utils import utcnow
from twitchtools.user import User
from twitchtools.subscription import TitleEvent
from twitchtools.stream import Stream
from time import time


from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import TwitchCallBackBot

class StreamStatus(commands.Cog):
    from twitchtools.files import get_title_callbacks, get_callbacks, get_title_cache, write_title_cache, get_channel_cache, write_channel_cache
    def __init__(self, bot):
        self.bot: TwitchCallBackBot = bot
        super().__init__()

    @commands.Cog.listener()
    async def on_title_change(self, event: TitleEvent):
        await self.bot.wait_until_ready()
        if not getattr(self.bot, "title_callbacks", None):
            self.bot.title_callbacks = await self.get_title_callbacks()
        if not self.bot.title_callbacks:
            return
        if not getattr(self.bot, "title_cache", None):
            self.bot.title_cache = await self.get_title_cache()
        old_title = self.bot.title_cache.get(event.broadcaster.username, {}).get("cached_title", "<no title>") #Get cached information for streamer, or none
        old_game = self.bot.title_cache.get(event.broadcaster.username, {}).get("cached_game", "<no game>")

        updated = [] #Quick way to make the dynamic embed title
        if event.title != old_title:
            updated.append("title")
        if event.game != old_game:
            updated.append("game")

        if updated == []: #If for some reason neither the title or game updated, just ignore
            self.bot.log.info(f"No title updates for {event.broadcaster.username}, ignoring")
            return

        self.bot.title_cache[event.broadcaster.username] = { #Update cached data
            "cached_title": event.title,
            "cached_game": event.game,
        }

        await self.write_title_cache(self.bot.title_cache)

        stream = await self.bot.api.get_stream(event.broadcaster.username)
        if stream:
            self.bot.log.info(f"{event.broadcaster.username} is live, ignoring title change")
            return

        #Create embed for discord
        embed = discord.Embed(description=f"{event.broadcaster.display_name} updated their {' and '.join(updated)}", colour=0x812BDC, timestamp=utcnow())
        if event.title != old_title:
            embed.add_field(name="Old Title", value=old_title, inline=True)
            embed.add_field(name="New Title", value=event.title, inline=True)
        if event.game != old_game:
            embed.add_field(name="Old Game", value=old_game, inline=True)
            embed.add_field(name="New Game", value=event.game, inline=True)
        embed.set_author(name=f"Stream Link", url=f"https://twitch.tv/{event.broadcaster.username}")
        embed.set_footer(text="Mew")

        self.bot.log.info(f"Sending title update for {event.broadcaster.username}")

        #Send embed to each defined channel
        for data in self.bot.title_callbacks[event.broadcaster.username]["alert_roles"].values():
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
                except discord.Forbidden:
                    pass
                except discord.HTTPException:
                    pass

    @commands.Cog.listener()
    async def on_streamer_offline(self, streamer: User):
        await self.bot.wait_until_ready()
        if not getattr(self.bot, "channel_cache", None):
            self.bot.channel_cache = await self.get_channel_cache()
        if not getattr(self.bot, "callbacks", None):
            self.bot.callbacks = await self.get_callbacks()
        if not self.bot.callbacks:
            return
        # Check if there's anything to even be done, if not, just return
        if self.bot.channel_cache.get(streamer.username, {}).get("live_channels", None) is None and self.bot.channel_cache.get(streamer.username, {}).get("live_alerts", None) is None:
            return
        self.bot.log.info(f"Updating status to offline for {streamer}")

        # Iterate through all live channels, if applicable, either deleting them or renaming them to stream-offline depending on mode
        for channel_id in self.bot.channel_cache[streamer.username].get("live_channels", []):
            channel = self.bot.get_channel(channel_id)
            if channel is not None:
                try:
                    if self.bot.callbacks[streamer.username]["alert_roles"][str(channel.guild.id)]["mode"] == 0:
                        await channel.delete()
                    elif self.bot.callbacks[streamer.username]["alert_roles"][str(channel.guild.id)]["mode"] == 2:
                        await channel.edit(name="stream-offline")
                except discord.Forbidden:
                    continue
                except discord.HTTPException:
                    continue
        
        # Delete live channel data after being used
        self.bot.channel_cache[streamer.username].pop("live_channels", None)
        
        # Just like channels, iterate through the sent live alerts, and make them past tense. 100% suseptible to edge cases
        for alert_ids in self.bot.channel_cache[streamer.username].get("live_alerts", []):
            channel = self.bot.get_channel(alert_ids["channel"])
            if channel is not None:
                try: #Try to get the live alerts message, skipping if not found
                    message = await channel.fetch_message(alert_ids["message"]) 
                except discord.NotFound:
                    continue
                else:
                    try: #Get the live alert embed, skipping it was removed, or something else happened
                        embed = message.embeds[0]
                    except IndexError:
                        continue
                    else:
                        try: #Replace the applicable strings with past tense phrasing
                            embed.set_author(name=embed.author.name.replace("is now live on Twitch!", "was live on Twitch!"), url=embed.author.url)
                            embed.description = f"was playing {embed.description.split('Playing ', 1)[1].split(' for', 1)[0]}"
                            try:
                                await message.edit(content=message.content.replace("is live on Twitch!", "was live on Twitch!"), embed=embed)
                            except discord.Forbidden: #In case something weird happens
                                continue
                        except IndexError: #In case something weird happens when parsing the embed values
                            self.bot.log.warning(f"Error editing message to offline in {channel.guild.name}")
        
        # Remove data once used
        self.bot.channel_cache[streamer.username].pop("live_alerts", None)

        # Update cache
        await self.write_channel_cache(self.bot.channel_cache)

    def on_cooldown(self, alert_cooldown: int) -> bool:
        if int(time()) - alert_cooldown < 600:
            return True
        return False

    @commands.Cog.listener()
    async def on_streamer_online(self, stream: Stream):
        await self.bot.wait_until_ready()
        if not getattr(self.bot, "channel_cache", None):
            self.bot.channel_cache = await self.get_channel_cache()
        if not getattr(self.bot, "callbacks", None):
            self.bot.callbacks = await self.get_callbacks()
        on_cooldown = self.on_cooldown(self.bot.channel_cache.get(stream.user.username, {}).get("alert_cooldown", 0))

        # Do not re-run this function is the streamer is already live
        if list(self.bot.channel_cache.get(stream.user.username, {"alert_cooldown": 0}).keys()) != ["alert_cooldown"]:
            self.bot.log.info(f"Ignoring alert while live for {stream.user.username}")
            return

        if on_cooldown: # There is a 10 minute cooldown between alerts, but live channels will still be created
            self.bot.log.info(f"Cooldown active, not sending alert for {stream.user.username} but creating channels")

        self.bot.log.info(f"Updating status to online for {stream.user.username}")

        # Sending webhook if applicable
        await self.do_webhook(self.bot.callbacks, stream)
        
        # Create embed message
        embed = discord.Embed(
            title=stream.title, url=f"https://twitch.tv/{stream.user.name}",
            description=f"Playing {stream.game} for {stream.view_count} viewers\n[Watch Stream](https://twitch.tv/{stream.user.name})",
            colour=8465372, timestamp=stream.started_at)
        embed.set_author(name=f"{stream.user.display_name} is now live on Twitch!", url=f"https://twitch.tv/{stream.user.name}")
        embed.set_footer(text="Mew")

        #Permission overrides
        SelfOverride = discord.PermissionOverwrite() # Make sure the bot has permission to access the channel
        SelfOverride.view_channel = True
        SelfOverride.send_messages = True
        DefaultRole = discord.PermissionOverwrite() # Deny @everyone access
        DefaultRole.view_channel = False
        DefaultRole.send_messages = False
        OverrideRole = discord.PermissionOverwrite() # Give users with the role access to view only
        OverrideRole.view_channel = True

        live_channels = []
        live_alerts = []
        for guild_id, alert_info in self.bot.callbacks[stream.user.username]["alert_roles"].items():
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
                        live_alert = await alert_channel.send(f"{stream.user.display_name} is live on Twitch!{role_mention}", embed=embed)
                        live_alerts.append({"channel": live_alert.channel.id, "message": live_alert.id})
                    except discord.Forbidden:
                        pass
                    except discord.HTTPException:
                        pass

            if alert_info["mode"] == 0: # Temporary live channel mode

                # Create channel overrides
                NewChannelOverrides = {self.bot.user: SelfOverride}
                if alert_info["role_id"] != "everyone":
                    NewChannelOverrides[guild.default_role] = DefaultRole
                if alert_info["role_id"] is not None and alert_info["role_id"] != "everyone":
                    NewChannelOverrides[role] = OverrideRole

                # Check if channel doesn't already exist. Kind of a bad idea, but does effectively prevent duplicate channels
                if f"🔴{stream.user.username}" not in [channel.name for channel in guild.text_channels]:
                    # Create temporary channel and add channel id to channel cache
                    try:
                        channel = await guild.create_text_channel(f"🔴{stream.user.username}", overwrites=NewChannelOverrides, position=0)
                        if channel is not None:
                            await channel.send(f"{stream.user.display_name} is live! https://twitch.tv/{stream.user.name}")
                            live_channels.append(channel.id)
                    except discord.Forbidden:
                        self.bot.log.warning(f"Permission error creating text channels in guild {guild.name}! ({stream.user.username})")
            
            # Permanent channel. Do the same as above, but modify the existing channel, instead of making a new one
            elif alert_info["mode"] == 2:
                channel = self.bot.get_channel(alert_info["channel_id"])
                if channel is not None:
                    try:
                        await channel.edit(name="🔴now-live")
                        live_channels.append(channel.id)
                    except discord.Forbidden:
                        self.bot.log.warning(f"Forbidden error updating {stream.user.username} in guild {channel.guild.name}")
                else:
                    self.bot.log.warning(f"Error fetching channel ID {alert_info['channel_id']} for {stream.user.username}1")
        
        #Finally, combine all data into channel cache, and update the file
        self.bot.channel_cache[stream.user.username] = {"alert_cooldown": int(time()), "live_channels": live_channels, "live_alerts": live_alerts}

        await self.write_channel_cache(self.bot.channel_cache)

    async def do_webhook(self, callbacks: dict, stream: Stream):
        if "webhook" in callbacks[stream.user.username].keys():
            if "format" in callbacks[stream.user.username].keys():
                format_ = callbacks[stream.user.username]["format"].format(stream).replace("\\n", "\n")
            else:
                format_ = f"{stream.user.display_name} is live! Playing {stream.game}!\nhttps://twitch.tv/{stream.user.username}"
            if type(callbacks[stream.user.username]["webhook"]) == list:
                for webhook in callbacks[stream.user.username]["webhook"]:
                    if discord.__version__ == "2.0.0a":
                        webhook_obj = discord.Webhook.from_url(webhook, session=self.bot.aSession)
                    else:
                        webhook_obj = discord.Webhook.from_url(webhook, session=discord.AsyncWebhookAdapter(self.bot.aSession))
                    try:
                        await webhook_obj.send(content=format_)
                    except discord.NotFound:
                        pass
            else:
                if discord.__version__ == "2.0.0a":
                    webhook = discord.Webhook.from_url(callbacks[stream.user.username]["webhook"], session=self.bot.aSession)
                else:
                    webhook_obj = discord.Webhook.from_url(callbacks[stream.user.username]["webhook"], session=discord.AsyncWebhookAdapter(self.bot.aSession))
                try:
                    await webhook.send(content=format_)
                except discord.NotFound:
                    pass

def setup(bot):
    bot.add_cog(StreamStatus(bot))
