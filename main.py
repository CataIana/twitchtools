from __future__ import annotations
from discord import Intents, Colour, Embed, PermissionOverwrite, NotFound, Webhook, Forbidden, Activity, ActivityType, HTTPException
import discord
from discord.ext import commands
from cogs.webserver import RecieverWebServer
from twitchtools.api import http
from aiohttp import ClientSession
from datetime import datetime
from json.decoder import JSONDecodeError
from time import time
import aiofiles
import logging
import json
import sys
from dislash import InteractionClient

class TwitchCallBackBot(commands.Bot):
    def __init__(self):
        intents = Intents.none()
        intents.guilds = True
        super().__init__(command_prefix=commands.when_mentioned_or("t!"), intents=intents, activity=Activity(type=ActivityType.listening, name="stream status"))

        self.log: logging.Logger = logging.getLogger("TwitchTools")
        self.log.setLevel(logging.INFO)

        shandler = logging.StreamHandler(sys.stdout)
        shandler.setLevel(logging.INFO)
        shandler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
        self.log.addHandler(shandler)

        self.slash: InteractionClient = InteractionClient(self)
        self.api: http = http(self, auth_file=f"config/auth.json")
        self.web_server: RecieverWebServer = RecieverWebServer(self)
        self.loop.run_until_complete(self.web_server.start())

        self.load_extension(f"cogs.reciever_bot_cogs")
        self.load_extension(f"cogs.emotes_sync")
        self.load_extension(f"cogs.error_listener")
        self.colour = Colour.from_rgb(128, 0, 128)
        with open("config/auth.json") as f:
            self.auth = json.load(f)
        self.token = self.auth["bot_token"]
        self._uptime = time()

    async def close(self):
        await self.aSession.close()
        self.log.info("Shutting down...")
        await super().close()

    @commands.Cog.listener()
    async def on_connect(self):
        self.aSession: ClientSession = ClientSession() #Make the aiohttp session asap

    @commands.Cog.listener()
    async def on_ready(self):
        self.log.info(f"------ Logged in as {self.user.name} - {self.user.id} ------")

    async def catchup_streamers(self):
        await self.wait_until_ready()
        try:
            async with aiofiles.open("config/callbacks.json") as f:
                callbacks = json.loads(await f.read())
        except FileNotFoundError:
            return
        except JSONDecodeError:
            return
        streams = await self.api.get_streams(user_ids=[c["channel_id"] for c in callbacks.values()])
        online_streams = [stream.user.id for stream in streams]
        for streamer, data in callbacks.items(): #Iterate through all callbacks and run
            if int(data["channel_id"]) in online_streams:
                await self.streamer_online(streamer, [x for x in streams if x.user.id == int(data["channel_id"])][0])
            else:
                await self.streamer_offline(streamer)

    async def title_change(self, streamer, stream_info):
        try:
            async with aiofiles.open("config/title_callbacks.json") as f:
                callbacks = json.loads(await f.read())
        except FileNotFoundError:
            self.bot.log.error("Failed to read title callbacks config file!")
            return
        except JSONDecodeError:
            self.bot.log.error("Failed to read title callbacks config file!")
            return
        try:
            async with aiofiles.open("cache/titlecache.cache") as f:
                title_cache = json.loads(await f.read())
        except FileNotFoundError:
            title_cache = {}
        except json.decoder.JSONDecodeError:
            title_cache = {}
        old_title = title_cache.get(streamer, {}).get("cached_title", "<no title>")
        old_game = title_cache.get(streamer, {}).get("cached_game", "<no game>")
        #Prevent errors with empty content values
        if stream_info["event"]["title"] == "":
            stream_info["event"]["title"] = "<no title>"
        if stream_info["event"]["category_name"] == "":
            stream_info["event"]["category_name"] = "<no game>"

        updated = [] #Quick way to make the dynamic title
        if stream_info["event"]["title"] != old_title:
            updated.append("title")
        if stream_info["event"]["category_name"] != old_game:
            updated.append("game")

        if updated == []: #If for some reason neither the title or game updated, just ignore
            self.log.info(f"No title updates for {streamer}, ignoring")
            return

        title_cache[streamer] = { #Update cached data
            "cached_title": stream_info["event"]["title"],
            "cached_game": stream_info["event"]["category_name"],
        }

        async with aiofiles.open("cache/titlecache.cache", "w") as f:
            await f.write(json.dumps(title_cache, indent=4))

        embed = Embed(description=f"{stream_info['event']['broadcaster_user_name']} updated their {' and '.join(updated)}", colour=0x812BDC, timestamp=datetime.utcnow())
        if stream_info["event"]["title"] != old_title:
            embed.add_field(name="Old Title", value=old_title, inline=True)
            embed.add_field(name="New Title", value=stream_info["event"]["title"], inline=True)
        if stream_info["event"]["category_name"] != old_game:
            embed.add_field(name="Old Game", value=old_game, inline=True)
            embed.add_field(name="New Game", value=stream_info["event"]["category_name"], inline=True)
        embed.set_author(name=f"Stream Link", url=f"https://twitch.tv/{stream_info['event']['broadcaster_user_login']}")
        embed.set_footer(text="Mew")

        self.log.info(f"Sending title update for {streamer}")

        for data in callbacks[streamer]["alert_roles"].values():
            c = self.get_channel(data["notif_channel_id"])
            if c is not None:
                if data['role_id'] is None:
                    role_mention = ""
                elif data["role_id"] == "everyone":
                    role_mention = "@everyone"
                else:
                    role_mention = f"<@&{data['role_id']}>"
                try:
                    await c.send(f"{role_mention}", embed=embed)
                except Forbidden:
                    pass
                except HTTPException:
                    pass
            else:
                self.log.warning("Invalid channel")


    async def streamer_offline(self, streamer):
        try:
            async with aiofiles.open("cache/channelcache.cache") as f:
                channel_cache = json.loads(await f.read())
        except FileNotFoundError:
            channel_cache = {}
        except json.decoder.JSONDecodeError:
            channel_cache = {}
        async with aiofiles.open("config/callbacks.json") as f:
            callback_info = json.loads(await f.read())
        if streamer in channel_cache.keys():
            if channel_cache[streamer].get("live_channels", None) is None or channel_cache[streamer].get("live_alerts", None) is None:
                return
            self.log.info(f"Updating status to offline for {streamer}")
            for channel_id in channel_cache[streamer].get("live_channels", []):
                channel = self.get_channel(channel_id)
                if channel is not None:
                    if callback_info[streamer]["alert_roles"][str(channel.guild.id)]["mode"] == 0:
                        await channel.delete()
                    elif callback_info[streamer]["alert_roles"][str(channel.guild.id)]["mode"] == 2:
                        await channel.edit(name="stream-offline")
            if channel_cache[streamer].get("live_channels", None) is not None:
                del channel_cache[streamer]["live_channels"]
            for alert_ids in channel_cache[streamer].get("live_alerts", []):
                channel = self.get_channel(alert_ids["channel"])
                if channel is not None:
                    try:
                        message = await channel.fetch_message(alert_ids["message"])
                    except NotFound:
                        pass
                    else:
                        try:
                            embed = message.embeds[0]
                        except IndexError:
                            pass
                        else:
                            try:
                                embed.set_author(name=embed.author.name.replace("is now live on Twitch!", "was live on Twitch!"), url=embed.author.url)
                                embed.description = f"was playing {embed.description.split('Playing ', 1)[1].split(' for', 1)[0]}"
                                await message.edit(content=message.content.replace("is live on Twitch!", "was live on Twitch!"), embed=embed)
                            except IndexError:
                                self.log.warning(f"Error editing message to offline in {channel.guild.name}")
            if channel_cache[streamer].get("live_alerts", None) is not None:
                del channel_cache[streamer]["live_alerts"]
            async with aiofiles.open("cache/channelcache.cache", "w") as f:
                await f.write(json.dumps(channel_cache, indent=4))

    async def streamer_online(self, streamer, stream_info):
        try:
            async with aiofiles.open("cache/channelcache.cache") as f:
                channel_cache = json.loads(await f.read())
        except FileNotFoundError:
            channel_cache = {}
        except json.decoder.JSONDecodeError:
            channel_cache = {}
        async with aiofiles.open("config/callbacks.json") as f:
            callback_info = json.loads(await f.read())
        only_channel = False
        if int(time()) - channel_cache.get(streamer, {}).get("alert_cooldown", 0) < 600:
            only_channel = True
        temp = dict(channel_cache.get(streamer, {"alert_cooldown": 0}))
        del temp["alert_cooldown"]
        if list(temp.keys()) != []:
            self.log.info(f"Ignoring alert while live for {streamer}")
            return
        if only_channel:
            self.log.info(f"Cooldown active, not sending alert for {streamer} but creating channels")
        self.log.info(f"Updating status to online for {streamer}")
        #Sending webhook if applicable
        if "webhook" in callback_info[streamer].keys():
            if "format" in callback_info[streamer].keys():
                format_ = callback_info[streamer]["format"].format(**stream_info).replace("\\n", "\n")
            else:
                format_ = f"{stream_info.user.display_name} is live! Playing {stream_info.game}!\nhttps://twitch.tv/{stream_info.user.name}"
            if type(callback_info[streamer]["webhook"]) == list:
                for webhook in callback_info[streamer]["webhook"]:
                    if discord.__version__ == "2.0.0a":
                        webhook_obj = Webhook.from_url(webhook, session=self.aSession)
                    else:
                        webhook_obj = Webhook.from_url(webhook, session=discord.AsyncWebhookAdapter(self.aSession))
                    try:
                        await webhook_obj.send(content=format_)
                    except NotFound:
                        pass
            else:
                if discord.__version__ == "2.0.0a":
                    webhook = Webhook.from_url(callback_info[streamer]["webhook"], session=self.aSession)
                else:
                    webhook_obj = Webhook.from_url(callback_info[streamer]["webhook"], session=discord.AsyncWebhookAdapter(self.aSession))
                try:
                    await webhook.send(content=format_)
                except NotFound:
                    pass
        #Send live alert message
        embed = Embed(
            title=stream_info.title, url=f"https://twitch.tv/{stream_info.user.name}",
            description=f"Playing {stream_info.game} for {stream_info.view_count} viewers\n[Watch Stream](https://twitch.tv/{stream_info.user.name})",
            colour=8465372, timestamp=stream_info.started_at)
        embed.set_author(name=f"{stream_info.user.display_name} is now live on Twitch!", url=f"https://twitch.tv/{stream_info.user.name}")
        embed.set_footer(text="Mew")
        SelfOverride = PermissionOverwrite()
        SelfOverride.view_channel = True
        SelfOverride.send_messages = True
        DefaultRole = PermissionOverwrite()
        DefaultRole.view_channel = False
        DefaultRole.send_messages = False
        OverrideRole = PermissionOverwrite()
        OverrideRole.view_channel = True
        live_channels = []
        live_alerts = []
        for guild_id, alert_info in callback_info[streamer]["alert_roles"].items():
            guild = self.get_guild(int(guild_id))
            if guild is not None:
                if alert_info["role_id"] == "everyone":
                    role_mention = f" {guild.default_role}"
                elif alert_info["role_id"] == None:
                    role_mention = ""
                else:
                    role = guild.get_role(alert_info["role_id"])
                    role_mention = f" {role.mention}"
                if not only_channel:
                    alert_channel_id = alert_info.get("channel_override", None)
                    if alert_channel_id == None:
                        alert_channel_id = alert_info.get("notif_channel_id", None)
                    alert_channel = self.get_channel(alert_channel_id)
                    if alert_channel is not None:
                        try:
                            live_alert = await alert_channel.send(f"{stream_info.user.display_name} is live on Twitch!{role_mention}", embed=embed)
                            live_alerts.append({"channel": live_alert.channel.id, "message": live_alert.id})
                        except Forbidden:
                            pass
                #Add channel to live alert list
                if alert_info["mode"] == 0:
                    NewChannelOverrides = {self.user: SelfOverride}
                    if alert_info["role_id"] != "everyone":
                        NewChannelOverrides[guild.default_role] = DefaultRole
                    if alert_info["role_id"] is not None and alert_info["role_id"] != "everyone":
                        NewChannelOverrides[role] = OverrideRole

                    if f"🔴{streamer}" not in [channel.name for channel in guild.text_channels]:
                        channel = await guild.create_text_channel(f"🔴{streamer}", overwrites=NewChannelOverrides, position=0)
                        if channel is not None:
                            try:
                                await channel.send(f"{stream_info.user.display_name} is live! https://twitch.tv/{stream_info.user.name}")
                                live_channels.append(channel.id)
                            except Forbidden:
                                self.log.warning(f"Forbidden error updating {streamer} in guild {guild.name}")
                        else:
                            self.log.warning(f"Error fetching channel ID {alert_info['channel_id']} for {streamer}")
                elif alert_info["mode"] == 2:
                    channel = self.get_channel(alert_info["channel_id"])
                    if channel is not None:
                        try:
                            await channel.edit(name="🔴now-live")
                            live_channels.append(channel.id)
                        except Forbidden:
                            self.log.warning(f"Forbidden error updating {streamer} in guild {channel.guild.name}")
                    else:
                        self.log.warning(f"Error fetching channel ID {alert_info['channel_id']} for {streamer}")
        channel_cache[streamer] = {"alert_cooldown": int(time()), "live_channels": live_channels, "live_alerts": live_alerts}
        async with aiofiles.open("cache/channelcache.cache", "w") as f:
            await f.write(json.dumps(channel_cache, indent=4))

if __name__ == "__main__":
    bot = TwitchCallBackBot()
    bot.run(bot.token)
