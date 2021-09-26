from discord import ChannelType, Embed, TextChannel, AllowedMentions, NotFound, Forbidden
from discord.ext import commands, tasks
import json
import asyncio
import requests
from datetime import datetime
from time import strftime, localtime, time
from types import BuiltinFunctionType, FunctionType, MethodType
from random import choice
from string import ascii_letters
import aiofiles

def is_mod():
    async def predicate(ctx):
        if ctx.author.id in [[ctx.cog.bot.owner_id] + list(ctx.cog.bot.owner_ids)]:
            return True
        return ctx.author.guild_permissions.manage_guild
    return commands.check(predicate)


def is_admin():
    async def predicate(ctx):
        if await ctx.bot.is_owner(ctx.author):
            return True
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

class RecieverCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
        self.bot.help_command = commands.MinimalHelpCommand()
        self.bot.help_command.cog = self
        self.backup_checks.start()

    def cog_unload(self):
        self.bot.help_command = self.bot.super().help_command
        self.backup_checks.cancel()

    @tasks.loop(seconds=600)
    async def backup_checks(self):
        self.bot.log.info("Running streamer catchup...")
        await self.bot.catchup_streamers()
        self.bot.log.info("Finished streamer catchup")

    @commands.Cog.listener()
    async def on_command(self, ctx):
        self.bot.log.info(f"Handling command {ctx.command.name} for {ctx.author} in {ctx.guild.name}")

    class CustomContext(commands.Context):
        async def send(self, content=None, **kwargs):
            no_reply_mention = AllowedMentions(replied_user=(
                True if self.author in self.message.mentions else False))
            kwargs.pop("hidden", None)
            return await self.reply(content, **kwargs, allowed_mentions=no_reply_mention)

        async def send_noreply(self, content=None, **kwargs):
            return await super().send(content, **kwargs)


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.content == "Pong!" and message.author == self.bot.user:
            rest = int(((datetime.utcnow() - message.created_at).microseconds)/1000)
            gateway = int(self.bot.latency*1000)
            await message.edit(content=f"Pong! `{rest}ms` Rest | `{gateway}ms` Gateway")

        if message.channel.type == ChannelType.private:
            return

        p = message.channel.permissions_for(message.guild.me)
        if not p.send_messages and not p.embed_links:
            return

        if message.author.bot or message.author == self.bot.user:
            return

        ctx = await self.bot.get_context(message, cls=self.CustomContext)
        await self.bot.invoke(ctx)

    @commands.command()
    @commands.cooldown(1, 2, commands.BucketType.member)
    async def ping(self, ctx):
        await ctx.send(content="Pong!") #Send the pong and let the message listener show the details

    @commands.command()
    @commands.is_owner()
    @commands.cooldown(1, 2, commands.BucketType.user)
    async def reload(self, ctx):
        await ctx.channel.trigger_typing()
        cog_count = 0
        for ext_name in dict(self.bot.extensions).keys():
            cog_count += 1
            self.bot.reload_extension(ext_name)
        await ctx.send(content=f"<:green_tick:809191812434231316> Succesfully reloaded! Reloaded {cog_count} cogs!")

    @commands.command()
    @commands.is_owner()
    async def catchup(self, ctx):
        self.bot.log.info("Running streamer catchup...")
        await self.bot.catchup_streamers()
        self.bot.log.info("Finished streamer catchup")
        await ctx.send("Finished catchup!")

    @commands.command()
    @commands.cooldown(1, 5, commands.BucketType.member)
    async def uptime(self, ctx):
        epoch = time() - self.bot._uptime
        conv = {
            "days": str(epoch // 86400).split('.')[0],
            "hours": str(epoch // 3600 % 24).split('.')[0],
            "minutes": str(epoch // 60 % 60).split('.')[0],
            "seconds": str(epoch % 60).split('.')[0],
            "full": strftime('%Y-%m-%d %I:%M:%S %p %Z', localtime(self.bot._uptime))
        }
        description = f"{conv['days']} {'day' if conv['days'] == '1' else 'days'}, {conv['hours']} {'hour' if conv['hours'] == '1' else 'hours'}, {conv['minutes']} {'minute' if conv['minutes'] == '1' else 'minutes'} and {conv['seconds']} {'second' if conv['seconds'] == '1' else 'seconds'}"
        embed = Embed(title="Uptime", description=description,
                            color=self.bot.colour, timestamp=datetime.utcnow())
        embed.set_footer(
            text=f"ID: {ctx.guild.id} | Bot started at {conv['full']}")
        await ctx.send(embed=embed)

    async def aeval(self, ctx, code):
        code_split = ""
        code_length = len(code.split("\\n"))
        for count, line in enumerate(code.split("\\n"), 1):
            if count == code_length:
                code_split += f"    return {line}"
            else:
                code_split += f"    {line}\n"
        combined = f"async def __ex(self, ctx):\n{code_split}"
        exec(combined)
        return await locals()['__ex'](self, ctx)

    @commands.command(description="Evaluate a string as a command", aliases=["evalr"])
    @commands.is_owner()
    async def eval(self, ctx, *, com):
        code_string = "```nim\n{}```"
        if com.startswith("`") and com.endswith("`"):
            com = com[1:][:-1]
        try:
            resp = await self.aeval(ctx, com)
        except Exception as ex:
            await ctx.send(content=f"Exception Occurred: `{ex}`")
        else:
            if not ctx.invoked_with == "evalr":
                if type(resp) == str:
                    return await ctx.send(code_string.format(resp))

                attributes = {} #Dict of all attributes
                methods = [] #Sync methods
                amethods = [] #Async methods
                #get a list of all attributes and their values, along with all the functions in seperate lists
                for attr_name in dir(resp):
                    try:
                        attr = getattr(resp, attr_name)
                    except AttributeError:
                        pass
                    if attr_name.startswith("_"):
                        continue #Most methods/attributes starting with __ or _ are generally unwanted, skip them
                    if type(attr) not in [MethodType, BuiltinFunctionType, FunctionType]:
                        attributes[str(attr_name)] = f"{attr} [{type(attr).__name__}]"
                    else:
                        if asyncio.iscoroutinefunction(attr):
                            amethods.append(attr_name)
                        else:
                            methods.append(attr_name)
                if attributes == {}:
                    attributes["str"] = str(resp)

                #Form the long ass string of everything
                return_string = []
                if type(resp) != list:
                    stred = str(resp)
                else:
                    stred = '\n'.join([str(r) for r in resp])
                return_string += [f"Type: {type(resp).__name__}", f"Str: {stred}", '', "Attributes:"] #List return type, it's str value
                return_string += [f"{x}:    {y}" for x, y in attributes.items()]

                if methods != []:
                    return_string.append("\nMethods:")
                    return_string.append(', '.join([method for method in methods]).rstrip(", "))

                if amethods != []:
                    return_string.append("\n\nAsync/Awaitable Methods:")
                    return_string.append(', '.join([method for method in amethods]).rstrip(", "))

                d_str = ""
                for x in return_string:
                    if len(d_str + f"{x.rstrip(', ')}\n") < 1990:
                        d_str += f"{x.rstrip(', ')}\n"
                    else:
                        if len(code_string.format(d_str)) > 2000:
                            while d_str != "":
                                await ctx.send(code_string.format(d_str[:1990]))
                                d_str = d_str[1990:]
                        else:
                            await ctx.send(code_string.format(d_str))
                        d_str = f"{x.rstrip(', ')}\n"
                if d_str != "":
                    try:
                        await ctx.send(code_string.format(d_str))
                    except NotFound:
                        pass

    @commands.command()
    @is_admin()
    async def alertchannel(self, ctx, channel: TextChannel = None):
        async with aiofiles.open("alert_channels.json") as f:
            alert_channels = json.loads(await f.read())
        if channel is None:
            alert_channel_id = alert_channels.get(str(ctx.guild.id), None)
            if alert_channel_id is None:
                await ctx.send("Alert channel for this guild is not set!")
                return
            alert_channel = self.bot.get_channel(alert_channel_id)
            if alert_channel is None:
                await ctx.send("Alert channel for this guild has been deleted or otherwise. This must be altered for alerts to continue functioning")
                return
            await ctx.send(f"Alert channel for this guild is {alert_channel.mention}")
        else:
            alert_channels[str(ctx.guild.id)] = channel.id
            async with aiofiles.open("alert_channels.json", "w") as f:
                await f.write(json.dumps(alert_channels, indent=4))
            await ctx.send(f"Alert channel for this guild was set to {channel.mention}")

    @commands.command()
    @is_admin()
    async def addstreamer(self, ctx):
        embed = Embed(
            title="Step 1 - Streamer",
            description="Please provide a twitch streamer url or username.",
            color=self.bot.colour
        )
        embed.set_footer(text="Setup will timeout after 3 minutes of no response.")
        setup_message = await ctx.send(embed=embed)
        def check(m):
            if ctx.author != m.author:
                return False
            twitch_username = m.content.split("/")[-1].lower()
            response = requests.get(url=f"https://api.twitch.tv/helix/users?login={twitch_username}", headers={"Client-ID": self.bot.auth["client_id"], "Authorization": f"Bearer {self.bot.auth['oauth']}"})
            json_obj = response.json()
            if len(json_obj["data"]) == 1:
                return True
        try:
            username_message = await self.bot.wait_for("message", timeout=180.0, check=check)
        except asyncio.TimeoutError:
            await setup_message.delete()
            return
        try:
            await username_message.delete()
        except Forbidden:
            pass
        twitch_username = username_message.content.split("/")[-1].lower()
        async with aiofiles.open("callbacks.json") as f:
            callbacks = json.loads(await f.read())
        
        warning = None
        if str(ctx.guild.id) in callbacks.get(twitch_username, {}).get("alert_roles", {}).keys():
            warning = await ctx.send_noreply("Warning. This streamer has already been setup for this channel. Continuing will override the previously set settings.")

        response = await self.bot.api_request(f"https://api.twitch.tv/helix/users?login={twitch_username}")
        json_obj = await response.json()
        twitch_userid = json_obj["data"][0]["id"]

        embed = Embed(
            title="Step 2 - Role",
            description=f"Please tag, write the name of, or the ID of the role you would like to be pinged when {twitch_username} goes live. If you do not want an role, type 'no'. If you want to mention everyone, type 'everyone'",
            color=self.bot.colour
        )
        await setup_message.edit(embed=embed)

        def check(m):
            if m.author == ctx.author and m.content in ["no", "everyone"]:
                return True
            if len(m.role_mentions) == 1 and m.author == ctx.author:
                return True
            try:
                int(m.content)
            except ValueError:
                if [role for role in ctx.guild.roles if role.name.lower() == m.content.lower()] != []:
                    return True
            else:
                if ctx.guild.get_role(int(m.content)) != None:
                    return True
        invalid_message_id = True
        while invalid_message_id:
            try:
                setup_role_msg = await self.bot.wait_for("message", timeout=180.0, check=check)
                if warning is not None:
                    await warning.delete()
                if setup_role_msg.content == "no":
                    invalid_message_id = False
                    alert_role = "no"
                    try:
                        await setup_role_msg.delete()
                    except Forbidden:
                        pass
                if setup_role_msg.content == "everyone":
                    invalid_message_id = False
                    alert_role = "everyone"
                    try:
                        await setup_role_msg.delete()
                    except Forbidden:
                        pass
                if len(setup_role_msg.role_mentions) == 1:
                    alert_role = setup_role_msg.role_mentions[0]
                    if alert_role.position < ctx.guild.me.top_role.position:
                        invalid_message_id = False
                    try:
                        await setup_role_msg.delete()
                    except Forbidden:
                        pass
                role = [role for role in ctx.guild.roles[1:] if role.name.lower() == setup_role_msg.content.lower()]
                if role != []:
                    alert_role = role[0]
                    invalid_message_id = False
                    try:
                        await setup_role_msg.delete()
                    except Forbidden:
                        pass
                    except NotFound:
                        pass
                try:
                    int(setup_role_msg.content)
                except ValueError:
                    pass
                else:
                    role = ctx.guild.get_role(int(setup_role_msg.content))
                    if role != None:
                        alert_role = role
                        invalid_message_id = False
                        try:
                            await setup_role_msg.delete()
                        except Forbidden:
                            pass
            except asyncio.TimeoutError:
                await setup_message.delete()
                return
        

        embed = Embed(
            title="Step 3 - Alert Mode",
            description=f"This bot supports 2 modes. Mode 0 sends only a notification. Mode 2 will send a notification and update a status channel. Please provide a mode you wish to select by entering the corresponding number",
            color=self.bot.colour
        )
        await setup_message.edit(embed=embed)

        def check(m):
            if m.author == ctx.author and m.content in ["0", "2"]:
                return True
        invalid_message_id = True
        while invalid_message_id:
            try:
                setup_mode_msg = await self.bot.wait_for("message", timeout=180.0, check=check)
                if setup_mode_msg.content in ["0", "2"]:
                    invalid_message_id = False
                    mode = int(setup_mode_msg.content)
                    try:
                        await setup_mode_msg.delete()
                    except Forbidden:
                        pass
                    except NotFound:
                        pass
            except asyncio.TimeoutError:
                await setup_message.delete()
                return

        if mode == 2:
            embed = Embed(
                title="Step 4 - Status Channel",
                description=f"Please tag the channel that you would like to be used as the status channel. When {twitch_username} goes live this channel will be renamed to `🔴now-live` and when they go offline it will be renamed to `stream-offline`",
                color=self.bot.colour
            )
            await setup_message.edit(embed=embed)
            def check(m):
                return ctx.author == m.author and len(m.channel_mentions) == 1
            try:
                channel_mention_message = await self.bot.wait_for("message", timeout=180.0, check=check)
            except asyncio.TimeoutError:
                await setup_message.delete()
                return
            try:
                await channel_mention_message.delete()
            except Forbidden:
                pass
            status_channel = channel_mention_message.channel_mentions[0]
            status_channel_perms = status_channel.permissions_for(ctx.guild.me)
            if status_channel_perms.view_channel == False:
                embed = Embed(
                title="Setup failed",
                description=f"Bot is unable to see {status_channel.mention}! Please check the bot permissions and try again.",
                color=self.bot.colour
                )
                await setup_message.edit(embed=embed)
                return
            if status_channel_perms.read_message_history == False:
                embed = Embed(
                title="Setup failed",
                description=f"Bot is unable to see message history in {status_channel.mention}! Please check the bot permissions and try again.",
                color=self.bot.colour
                )
                await setup_message.edit(embed=embed)
                return
            if status_channel_perms.send_messages == False:
                embed = Embed(
                title="Setup failed",
                description=f"Bot is unable to send messages in {status_channel.mention}! Please check the bot permissions and try again.",
                color=self.bot.colour
                )
                await setup_message.edit(embed=embed)
                return
        else:
            status_channel = None

        
        async with aiofiles.open("alert_channels.json") as f:
            alert_channels = json.loads(await f.read())

        if mode == 0:
            alert_channel_id = alert_channels.get(str(ctx.guild.id), None)
            if alert_channel_id is None:
                await ctx.send("Warning: The alert channel is not defined for this guild! You must set an alert channel or there will be no alerts!")
            else:
                alert_channel = self.bot.get_channel(alert_channel_id)
                if alert_channel is None:
                    await ctx.send("Warning: The alert channel is properly defined for this guild! You must set an alert channel or there will be no alerts!")

        if twitch_username not in callbacks.keys():
            callbacks[twitch_username] = {"channel_id": twitch_userid, "secret": await random_string_generator(21), "alert_roles": {}}
            response = await self.bot.api_request("https://api.twitch.tv/helix/eventsub/subscriptions",
                json={
                    "type": "stream.online",
                    "version": "1",
                    "condition": {
                        "broadcaster_user_id": twitch_userid
                    },
                    "transport": {
                        "method": "webhook",
                        "callback": f"{self.bot.auth['callback_url']}/callback/{twitch_username}",
                        "secret": callbacks[twitch_username]["secret"]
                    }
                }, method="post")
            response2 = await self.bot.api_request("https://api.twitch.tv/helix/eventsub/subscriptions",
                json={
                    "type": "stream.offline",
                    "version": "1",
                    "condition": {
                        "broadcaster_user_id": twitch_userid
                    },
                    "transport": {
                        "method": "webhook",
                        "callback": f"{self.bot.auth['callback_url']}/callback/{twitch_username}",
                        "secret": callbacks[twitch_username]["secret"]
                    }
                }, method="post")
            if response.status not in [202, 409]:
                return await ctx.send(f"There was an error subscribing to the stream online eventsub. Please try again later. Error code: {response.status_code}")
            if response2.status not in [202, 409]:
                return await ctx.send(f"There was an error subscribing to the stream online eventsub. Please try again later. Error code: {response.status_code}")
            json1 = await response.json()
            json2 = await response2.json()
            callbacks[twitch_username]["online_id"] = json1["data"][0]["id"]
            callbacks[twitch_username]["offline_id"] = json2["data"][0]["id"]
        callbacks[twitch_username]["alert_roles"][str(ctx.guild.id)] = {"mode": mode}
        if alert_role == "everyone":
            callbacks[twitch_username]["alert_roles"][str(ctx.guild.id)]["role_id"] = "everyone"
            alert_role_string = "@everyone"
        elif alert_role == "no":
            callbacks[twitch_username]["alert_roles"][str(ctx.guild.id)]["role_id"] = None
            alert_role_string = "No Role"
        else:
            callbacks[twitch_username]["alert_roles"][str(ctx.guild.id)]["role_id"] = alert_role.id
            alert_role_string = alert_role.mention
        if mode == 2:
            callbacks[twitch_username]["alert_roles"][str(ctx.guild.id)]["channel_id"] = status_channel.id


        async with aiofiles.open("callbacks.json", "w") as f:
            await f.write(json.dumps(callbacks, indent=4))

        response = await self.bot.api_request(f"https://api.twitch.tv/helix/streams?user_login={twitch_username}")
        response = await response.json()
        if response["data"] == []:
            if status_channel is not None:
                await status_channel.edit(name="stream-offline")
            await self.bot.streamer_offline(twitch_username)
        else:
            await self.bot.streamer_online(twitch_username, response["data"][0])
        
        embed = Embed(
            title="Setup Complete",
            color=self.bot.colour
        )
        embed.add_field(name="Streamer", value=twitch_username, inline=True)
        embed.add_field(name="Alert Role", value=alert_role_string, inline=True)
        embed.add_field(name="Alert Mode", value=mode, inline=True)
        if mode == 2:
            embed.add_field(name="Status Channel", value=status_channel.mention, inline=True)
        await setup_message.edit(embed=embed)

    @commands.command(aliases=["streamers"])
    @is_admin()
    async def liststreamers(self, ctx):
        async with aiofiles.open("callbacks.json") as f:
            callback_info = json.loads(await f.read())
        async with aiofiles.open("alert_channels.json") as f:
            alert_channels = json.loads(await f.read())

        alert_channel = self.bot.get_channel(alert_channels.get(str(ctx.guild.id), None))
        if alert_channel is not None:
            alert_channel = alert_channel.mention
        uwu = f"Guild Alert Channel: {alert_channel}```nim\n{'Channel':15s} {'Alert Role':25s} {'Alert Channel':18s} Alert Mode \n"
        for x, y in callback_info.items():
            if str(ctx.guild.id) in y["alert_roles"].keys():
                info = y["alert_roles"][str(ctx.guild.id)]
                alert_role = info.get("role_id", "")
                if alert_role is None:
                    alert_role = "<No Alert Role>"
                else:
                    try:
                        int(alert_role)
                    except ValueError:
                        pass
                    else:
                        alert_role = ctx.guild.get_role(alert_role)
                        if alert_role is not None:
                            alert_role = alert_role.name
                        else:
                            alert_role = ""

                channel_override = info.get("channel_override", None)
                channel_override = ctx.guild.get_channel(channel_override)
                if channel_override is not None:
                    channel_override = "#" + channel_override.name
                else:
                    channel_override = ""

                if len(uwu + f"{x:15s} {alert_role:25s} {channel_override:18s} {info.get('mode', 2)}\n") > 1800:
                    uwu += "```"
                    await ctx.send(uwu)
                    uwu = "```nim\n"
                uwu += f"{x:15s} {alert_role:25s} {channel_override:18s} {info.get('mode', 2)}\n"
        uwu += "```"
        await ctx.send(uwu)

    @commands.command(aliases=["titlechanges"])
    @is_admin()
    async def listtitlechanges(self, ctx):
        async with aiofiles.open("title_callbacks.json") as f:
            callback_info = json.loads(await f.read())

        uwu = f"```nim\n{'Channel':15s} {'Alert Role':35s} {'Alert Channel':18s}\n"
        for x, y in callback_info.items():
            if str(ctx.guild.id) in y["alert_roles"].keys():
                info = y["alert_roles"][str(ctx.guild.id)]
                alert_role = info.get("role_id", "")
                if alert_role is None:
                    alert_role = "<No Alert Role>"
                else:
                    try:
                        int(alert_role)
                    except ValueError:
                        pass
                    else:
                        alert_role = ctx.guild.get_role(alert_role)
                        if alert_role is not None:
                            alert_role = alert_role.name
                        else:
                            alert_role = ""

                alert_channel = info.get("channel_id", None)
                alert_channel = ctx.guild.get_channel(alert_channel)
                if alert_channel is not None:
                    alert_channel = "#" + alert_channel.name
                else:
                    alert_channel = ""

                if len(uwu + f"{x:15s} {alert_role:35s} {alert_channel:18s}\n") > 1800:
                    uwu += "```"
                    await ctx.send(uwu)
                    uwu = "```nim\n"
                uwu += f"{x:15s} {alert_role:35s} {alert_channel:18s}\n"
        uwu += "```"
        await ctx.send(uwu)

    @commands.command(aliases=["delstreamer"])
    @is_admin()
    async def removestreamer(self, ctx, streamer: str):
        async with aiofiles.open("callbacks.json") as f:
            callbacks = json.loads(await f.read())
        try:
            del callbacks[streamer]["alert_roles"][str(ctx.guild.id)]
        except KeyError:
            embed = Embed(title="Error", description="Username not found for guild.", colour=self.bot.colour)
            await ctx.send(embed=embed)
            return
        if callbacks[streamer]["alert_roles"] == {}:
            self.bot.log.info(f"Streamer {streamer} has no more alerts, purging")
            try:
                await self.bot.api_request(f"https://api.twitch.tv/helix/eventsub/subscriptions?id={callbacks[streamer]['offline_id']}", method="delete")
                await self.bot.api_request(f"https://api.twitch.tv/helix/eventsub/subscriptions?id={callbacks[streamer]['online_id']}", method="delete")
            except KeyError:
                pass
            del callbacks[streamer]
        async with aiofiles.open("callbacks.json", "w") as f:
            await f.write(json.dumps(callbacks, indent=4))
        embed = Embed(title="Streamer Removed", description=f"Deleted alert for {streamer}", colour=self.bot.colour)
        await ctx.send(embed=embed)

    @commands.command()
    @is_admin()
    async def addtitlechange(self, ctx):
        embed = Embed(
            title="Step 1 - Streamer",
            description="Please provide a twitch streamer url or username.",
            color=self.bot.colour
        )
        embed.set_footer(text="Setup will timeout after 3 minutes of no response.")
        setup_message = await ctx.send(embed=embed)
        def check(m):
            if ctx.author != m.author:
                return False
            twitch_username = m.content.split("/")[-1].lower()
            response = requests.get(url=f"https://api.twitch.tv/helix/users?login={twitch_username}", headers={"Client-ID": self.bot.auth["client_id"], "Authorization": f"Bearer {self.bot.auth['oauth']}"})
            json_obj = response.json()
            if len(json_obj["data"]) == 1:
                return True
        try:
            username_message = await self.bot.wait_for("message", timeout=180.0, check=check)
        except asyncio.TimeoutError:
            await setup_message.delete()
            return
        try:
            await username_message.delete()
        except Forbidden:
            pass
        twitch_username = username_message.content.split("/")[-1].lower()
        async with aiofiles.open("title_callbacks.json") as f:
            callbacks = json.loads(await f.read())
        
        warning = None
        if str(ctx.guild.id) in callbacks.get(twitch_username, {}).get("alert_roles", {}).keys():
            warning = await ctx.send_noreply("Warning. This streamer has already been setup for this channel. Continuing will override the previously set settings.")

        response = await self.bot.api_request(f"https://api.twitch.tv/helix/users?login={twitch_username}", method="get")
        json_obj = await response.json()
        twitch_userid = json_obj["data"][0]["id"]

        embed = Embed(
            title="Step 2 - Role",
            description=f"Please tag, write the name of, or the ID of the role you would like to be pinged when {twitch_username} changes their title. If you do not want an role, type 'no'. If you want to mention everyone, type 'everyone'",
            color=self.bot.colour
        )
        await setup_message.edit(embed=embed)

        def check(m):
            if m.author == ctx.author and m.content in ["no", "everyone"]:
                return True
            if len(m.role_mentions) == 1 and m.author == ctx.author:
                return True
            try:
                int(m.content)
            except ValueError:
                if [role for role in ctx.guild.roles if role.name.lower() == m.content.lower()] != []:
                    return True
            else:
                if ctx.guild.get_role(int(m.content)) != None:
                    return True
        invalid_message_id = True
        while invalid_message_id:
            try:
                setup_role_msg = await self.bot.wait_for("message", timeout=180.0, check=check)
                if warning is not None:
                    await warning.delete()
                if setup_role_msg.content == "no":
                    invalid_message_id = False
                    alert_role = "no"
                    try:
                        await setup_role_msg.delete()
                    except Forbidden:
                        pass
                if setup_role_msg.content == "everyone":
                    invalid_message_id = False
                    alert_role = "everyone"
                    try:
                        await setup_role_msg.delete()
                    except Forbidden:
                        pass
                if len(setup_role_msg.role_mentions) == 1:
                    alert_role = setup_role_msg.role_mentions[0]
                    if alert_role.position < ctx.guild.me.top_role.position:
                        invalid_message_id = False
                    try:
                        await setup_role_msg.delete()
                    except Forbidden:
                        pass
                role = [role for role in ctx.guild.roles[1:] if role.name.lower() == setup_role_msg.content.lower()]
                if role != []:
                    alert_role = role[0]
                    invalid_message_id = False
                    try:
                        await setup_role_msg.delete()
                    except Forbidden:
                        pass
                    except NotFound:
                        pass
                try:
                    int(setup_role_msg.content)
                except ValueError:
                    pass
                else:
                    role = ctx.guild.get_role(int(setup_role_msg.content))
                    if role != None:
                        alert_role = role
                        invalid_message_id = False
                        try:
                            await setup_role_msg.delete()
                        except Forbidden:
                            pass
            except asyncio.TimeoutError:
                await setup_message.delete()
                return
    
        embed = Embed(
            title="Step 3 - Notification Channel",
            description=f"Please tag the channel that you would like notifcations to be sent in.",
            color=self.bot.colour
        )
        await setup_message.edit(embed=embed)
        def check(m):
            return ctx.author == m.author and len(m.channel_mentions) == 1
        valid = False
        temp = None
        while not valid:
            try:
                notification_channel_message = await self.bot.wait_for("message", timeout=180.0, check=check)
            except asyncio.TimeoutError:
                await setup_message.delete()
                return
            try:
                await notification_channel_message.delete()
            except Forbidden:
                pass
            if temp is not None:
                await temp.delete()
            notification_channel = notification_channel_message.channel_mentions[0]
            notification_channel_perms = notification_channel.permissions_for(ctx.guild.me)
            if notification_channel_perms.view_channel == False:
                embed = Embed(
                title="Bad permissions!",
                description=f"Bot is unable to see {notification_channel.mention}! Please check the bot permissions and try again.",
                color=self.bot.colour
                )
                temp = await ctx.send(embed=embed)
                valid = False
                continue
            if notification_channel_perms.read_message_history == False:
                embed = Embed(
                title="Bad permissions!",
                description=f"Bot is unable to see message history in {notification_channel.mention}! Please check the bot permissions and try again.",
                color=self.bot.colour
                )
                temp = await ctx.send(embed=embed)
                valid = False
                continue
            if notification_channel_perms.send_messages == False:
                embed = Embed(
                title="Bad permissions!",
                description=f"Bot is unable to send messages in {notification_channel.mention}! Please check the bot permissions and try again.",
                color=self.bot.colour
                )
                temp = await ctx.send(embed=embed)
                valid = False
                continue
            valid = True
    

        if twitch_username not in callbacks.keys():
            callbacks[twitch_username] = {"channel_id": twitch_userid, "secret": await random_string_generator(21), "alert_roles": {}}
            response = await self.bot.api_request("https://api.twitch.tv/helix/eventsub/subscriptions",
                json={
                    "type": "channel.update",
                    "version": "1",
                    "condition": {
                        "broadcaster_user_id": twitch_userid
                    },
                    "transport": {
                        "method": "webhook",
                        "callback": f"{self.bot.auth['callback_url']}/titlecallback/{twitch_username}",
                        "secret": callbacks[twitch_username]["secret"]
                    }
                }, method="post")
            if response.status not in [202, 409]:
                return await ctx.send(f"There was an error subscribing to the stream online eventsub. Please try again later. Error code: {response.status} {await response.json()}")
            json1 = await response.json()
            callbacks[twitch_username]["subscription_id"] = json1["data"][0]["id"]
        callbacks[twitch_username]["alert_roles"][str(ctx.guild.id)] = {}
        if alert_role == "everyone":
            callbacks[twitch_username]["alert_roles"][str(ctx.guild.id)]["role_id"] = "everyone"
            alert_role_string = "@everyone"
        elif alert_role == "no":
            callbacks[twitch_username]["alert_roles"][str(ctx.guild.id)]["role_id"] = None
            alert_role_string = "No Role"
        else:
            callbacks[twitch_username]["alert_roles"][str(ctx.guild.id)]["role_id"] = alert_role.id
            alert_role_string = alert_role.mention
        callbacks[twitch_username]["alert_roles"][str(ctx.guild.id)]["channel_id"] = notification_channel.id


        async with aiofiles.open("title_callbacks.json", "w") as f:
            await f.write(json.dumps(callbacks, indent=4))
        
        embed = Embed(
            title="Setup Complete",
            color=self.bot.colour
        )
        embed.add_field(name="Streamer", value=twitch_username, inline=True)
        embed.add_field(name="Alert Role", value=alert_role_string, inline=True)
        embed.add_field(name="Notification Channel", value=notification_channel.mention, inline=True)
        await setup_message.edit(embed=embed)

    @commands.command(aliases=["deltitlechange"])
    @is_admin()
    async def removetitlechange(self, ctx, streamer: str):
        async with aiofiles.open("title_callbacks.json") as f:
            callbacks = json.loads(await f.read())
        try:
            del callbacks[streamer]["alert_roles"][str(ctx.guild.id)]
        except KeyError:
            embed = Embed(title="Error", description="Username not found for guild.", colour=self.bot.colour)
            await ctx.send(embed=embed)
            return
        if callbacks[streamer]["alert_roles"] == {}:
            self.bot.log.info(f"Streamer {streamer} has no more alerts, purging")
            try:
                await self.bot.api_request(f"https://api.twitch.tv/helix/eventsub/subscriptions?id={callbacks[streamer]['subscription_id']}", method="delete")
            except KeyError:
                pass
            del callbacks[streamer]
        async with aiofiles.open("title_callbacks.json", "w") as f:
            await f.write(json.dumps(callbacks, indent=4))
        embed = Embed(title="Streamer Removed", description=f"Deleted title change alert for {streamer}", colour=self.bot.colour)
        await ctx.send(embed=embed)

            
async def random_string_generator(str_size):
    return "".join(choice(ascii_letters) for _ in range(str_size))


# from discord.ext import tasks, commands

# class SubscribeLoop(commands.Cog): #This will trigger straight away after a restart. Undesirable
#     def __init__(self, bot):
#         self.bot = bot
#         self.subscriber.start()

#     def cog_unload(self):
#         self.subscriber.cancel()

#     @tasks.loop(hours=168)
#     async def subscriber(self):
#         print(self.index)
#         self.index += 1

#     @subscriber.before_loop
#     async def before_subscriber(self):
#         await self.bot.wait_until_ready()

def setup(bot):
    bot.add_cog(RecieverCommands(bot))