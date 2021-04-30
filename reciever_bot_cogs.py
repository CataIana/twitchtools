from discord import ChannelType, Embed, TextChannel, AllowedMentions
from discord.ext import commands
import requests
import json
from datetime import datetime
from time import strftime, localtime, time
from types import BuiltinFunctionType, FunctionType, MethodType
from random import choice
from string import ascii_letters

class RecieverCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    @commands.Cog.listener()
    async def on_command(self, ctx):
        self.bot.log.info(f"Handling command {ctx.command.name} for {ctx.author} in {ctx.guild.name}")

    @commands.Cog.listener()
    async def on_slash_command(self, ctx):
        self.bot.log.info(f"Handling slash command {ctx.command} for {ctx.author} in {ctx.guild.name}")

    class CustomContext(commands.Context):
        async def send(self, content=None, **kwargs):
            no_reply_mention = AllowedMentions(replied_user=(
                True if self.author in self.message.mentions else False))
            kwargs.pop("hidden", None)
            # if self.bot.server_dict[str(self.guild.id)]["delete_commands"]:
            #     return await super().send(content, **kwargs, allowed_mentions=no_reply_mention)
            # else:
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
        await ctx.send(content="Pong!")

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
        for count, line in enumerate(code.split("\\n")):
            if count+1 == code_length:
                code_split += f"    return {line}"
            else:
                code_split += f"    {line}\n"
        combined = f"async def __ex(self, ctx):\n{code_split}"
        self.bot.log.debug("Processed")
        exec(combined)
        return await locals()['__ex'](self, ctx)

    @commands.command()
    @commands.is_owner()
    async def eval(self, ctx, *, com):
        code_string = "```nim\n{}```"
        # if com.startswith("await "):
        #     com = com.lstrip("await ")
        try:
            #resp = eval(com, {"__builtins__": {}, "self": self, "ctx": ctx}, {})  #For sending without globals and locals
            # resp = eval(com)
            # if inspect.isawaitable(resp):
            #     resp = await resp
            resp = await self.aeval(ctx, com)
        except Exception as ex:
            await ctx.send(content=f"Exception Occurred: `{ex}`")
        else:
            if type(resp) == dict:
                d = resp
            elif type(resp) == list:
                d = resp
            else:
                d = {}
                for att in dir(resp):
                    try:
                        attr = getattr(resp, att)
                    except AttributeError:
                        pass
                    if not att.startswith("__") and type(attr) not in [MethodType, BuiltinFunctionType, FunctionType]:
                        d[str(att)] = f"{attr} [{type(attr).__name__}]"
                if d == {}:
                    d["str"] = str(resp)
            if type(d) == list:
                d_str = "List:\n"
                for x in d:
                    if len(d_str + f"{x}\n") < 1990:
                        d_str += f"{x}\n"
                    else:
                        await ctx.send(content=code_string.format(d_str))
                        d_str = ""
                        if len(d_str + f"{x}\n") < 1990:
                            d_str += f"{x}\n"
            else:
                d_str = ""
                for x, y in d.items():
                    if len(d_str + f"{x}:    {y}\n") < 1990:
                        d_str += f"{x}:    {y}\n"
                    else:
                        await ctx.send(content=code_string.format(d_str))
                        d_str = ""
                        if len(d_str + f"{x}:    {y}\n") < 1990:
                            d_str += f"{x}:    {y}\n"
            if d_str != "":
                await ctx.send(content=code_string.format(d_str))

    @commands.command()
    @commands.is_owner()
    async def alertchannel(self, ctx, channel: TextChannel = None):
        with open("alert_channels.json") as f:
            alert_channels = json.load(f)
        if channel is None:
            alert_channel_id = alert_channels.get(str(ctx.guild.id), None)
            if alert_channel_id is None:
                await ctx.send("Alert channel for this guild is not defined!")
                return
            alert_channel = self.bot.get_channel(alert_channel_id)
            if alert_channel is None:
                await ctx.send("Alert channel for this guild has been deleted or otherwise. This must be altered for alerts to continue functioning")
                return
            await ctx.send(f"Alert channel for this guild is {alert_channel.mention}")
        else:
            alert_channels[str(ctx.guild.id)] = channel.id
            with open("alert_channels.json", "w") as f:
                f.write(json.dumps(alert_channels, indent=4))
            await ctx.send(f"Alert channel for this guild was set to {channel.mention}")

    @commands.command()
    @commands.is_owner()
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
            response = requests.get(url=f"https://api.twitch.tv/kraken/users?login={twitch_username}", headers={"Accept": "application/vnd.twitchtv.v5+json", "Client-ID": self.bot.auth["client_id"]})
            json_obj = response.json()
            if len(json_obj["users"]) == 1:
                return True
        try:
            username_message = await self.bot.wait_for("message", timeout=180.0, check=check)
        except TimeoutError:
            await setup_message.delete()
            return
        await username_message.delete()
        twitch_username = username_message.content.split("/")[-1].lower()
        with open("callbacks.json") as f:
            callbacks = json.load(f)
        for x, y in callbacks.items():
            if str(ctx.guild.id) in y["alert_roles"]:
                warning = await ctx.send_noreply("Warning. This streamer has already been setup for this channel. Continuing will override the previously set settings.")

        response = await self.bot.aSession.get(url=f"https://api.twitch.tv/kraken/users?login={twitch_username}", headers={"Accept": "application/vnd.twitchtv.v5+json", "Client-ID": self.bot.auth["client_id"]})
        json_obj = await response.json()
        twitch_userid = json_obj["users"][0]["_id"]

        embed = Embed(
            title="Step 2 - Channel",
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
                await warning.delete()
                if setup_role_msg.content == "no":
                    invalid_message_id = False
                    alert_role = None
                    await setup_role_msg.delete()
                if setup_role_msg.content == "everyone":
                    invalid_message_id = False
                    alert_role = "everyone"
                    await setup_role_msg.delete()
                if len(setup_role_msg.role_mentions) == 1:
                    alert_role = setup_role_msg.role_mentions[0]
                    if alert_role.position < ctx.guild.me.top_role.position:
                        invalid_message_id = False
                    await setup_role_msg.delete()
                role = [role for role in ctx.guild.roles[1:] if role.name.lower() == setup_role_msg.content.lower()]
                if role != []:
                    alert_role = role[0]
                    if alert_role.position < ctx.guild.me.top_role.position:
                        invalid_message_id = False
                    await setup_role_msg.delete()
                try:
                    int(setup_role_msg.content)
                except ValueError:
                    pass
                else:
                    role = ctx.guild.get_role(int(setup_role_msg.content))
                    if role != None:
                        alert_role = role
                        if alert_role.position < ctx.guild.me.top_role.position:
                            invalid_message_id = False
                            await setup_role_msg.delete()
            except TimeoutError:
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
                    await setup_mode_msg.delete()
            except TimeoutError:
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
            except TimeoutError:
                await setup_message.delete()
                return
            await channel_mention_message.delete()
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

        
        with open("alert_channels.json") as f:
            alert_channels = json.load(f)

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
            response = requests.post("https://api.twitch.tv/helix/webhooks/hub",
                data={
                    "hub.callback": f"https://twitch-callback.catalana.dev/callback/{twitch_username}",
                    "hub.mode": "subscribe",
                    "hub.topic": f"https://api.twitch.tv/helix/streams?user_id={twitch_userid}",
                    "hub.lease_seconds": "691200",
                    "hub.secret": callbacks[twitch_username]["secret"]
                }, headers={"Authorization": f"Bearer {self.bot.auth['oauth']}", "Client-Id": self.bot.auth["client_id"]})
            if response.status_code != 202:
                await ctx.send("There was an error subscribing to the pubsub. Please try again later.")
                return
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


        with open("callbacks.json", "w") as f:
            f.write(json.dumps(callbacks, indent=4))

        response = await (await self.bot.aSession.get(url=f"https://api.twitch.tv/helix/streams?user_login={twitch_username}", headers={"Authorization": f"Bearer {self.bot.auth['oauth']}", "Client-Id": self.bot.auth["client_id"]})).json()
        if response["data"] == []:
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

    @commands.command()
    @commands.is_owner()
    async def liststreamers(self, ctx):
        with open("callbacks.json") as f:
            callback_info = json.load(f)
        with open("alert_channels.json") as f:
            alert_channels = json.load(f)
        alert_channel = self.bot.get_channel(alert_channels.get(str(ctx.guild.id), None))
        if alert_channel is not None:
            alert_channel = alert_channel.mention
        streamers = []
        streamers.append(f"Guild Alert Channel: {alert_channel}\n\n")
        for x, y in callback_info.items():
            if str(ctx.guild.id) in y["alert_roles"].keys():
                role = ctx.guild.get_role(y['alert_roles'][str(ctx.guild.id)]['role_id'])
                status_channel = ctx.guild.get_channel(y['alert_roles'][str(ctx.guild.id)].get('channel_id', None))
                if status_channel is not None:
                    status_channel_extras = f"Live Status Channel: {status_channel.name} `{status_channel.id if status_channel is not None else None}`"
                else:
                    status_channel_extras = None
                streamers.append(f"{x}: Alert Role: {role.name if role is not None else None} `{y['alert_roles'][str(ctx.guild.id)]['role_id']}` Alert Mode: {y['alert_roles'][str(ctx.guild.id)]['mode']} {status_channel_extras}")
        if len(streamers) == 1:
            await ctx.send(f"There are no streamers defined for this guild!\nGuild Alert Channel: {alert_channel}")
            return
        lol = '\n'.join(streamers)
        await ctx.send(f"```nim\n{lol}```")

    @commands.command(aliases=["delstreamer"])
    @commands.is_owner()
    async def removestreamer(self, ctx, streamer: str):
        with open("callbacks.json") as f:
            callbacks = json.load(f)
        try:
            del callbacks[streamer]["alert_roles"][str(ctx.guild.id)]
        except KeyError:
            embed = Embed(title="Error", description="Username not found for guild.", colour=self.bot.colour)
            await ctx.send(embed=embed)
            return
        if callbacks[streamer]["alert_roles"] == {}:
            del callbacks[streamer]
        with open("callbacks.json", "w") as f:
            f.write(json.dumps(callbacks, indent=4))
        embed = Embed(title="Streamer Removed", description=f"Deleted alert for {streamer}", colour=self.bot.colour)
        await ctx.send(embed=embed)

            
async def random_string_generator(str_size):
    return "".join(choice(ascii_letters) for x in range(str_size))


from discord.ext import tasks, commands

class SubscribeLoop(commands.Cog): #This will trigger straight away after a restart. Undesirable
    def __init__(self, bot):
        self.bot = bot
        self.subscriber.start()

    def cog_unload(self):
        self.subscriber.cancel()

    @tasks.loop(hours=168)
    async def subscriber(self):
        print(self.index)
        self.index += 1

    @subscriber.before_loop
    async def before_subscriber(self):
        await self.bot.wait_until_ready()

def setup(bot):
    bot.add_cog(RecieverCommands(bot))