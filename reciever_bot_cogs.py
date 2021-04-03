from discord import ChannelType, Embed
from discord.ext import commands
import inspect
import requests
import json
from datetime import datetime
from time import strftime, localtime, time
from types import BuiltinFunctionType, FunctionType, MethodType

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

        ctx = await self.bot.get_context(message)
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

    @commands.command()
    @commands.is_owner()
    async def eval(self, ctx, *, com):
        code_string = "```\n{}```"
        if com.startswith("await "):
            com = com.lstrip("await ")
        try:
            #resp = eval(com, {"__builtins__": {}, "self": self, "ctx": ctx}, {})
            resp = eval(com)
            if inspect.isawaitable(resp):
                resp = await resp
        except Exception as ex:
            await ctx.send(content=f"`{ex}`")
        else:
            d = {}
            for att in dir(resp):
                attr = getattr(resp, att)
                if not att.startswith("__") and type(attr) not in [MethodType, BuiltinFunctionType, FunctionType]:
                    d[str(att)] = f"{attr} [{type(attr).__name__}]"
            if d == {}:
                d["str"] = str(resp)
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
    async def addstreamer(self, ctx):
        embed = Embed(
            title="Step 1 - Streamer",
            description="Please provide a twitch streamer url or username.",
            color=self.bot.colour
        )
        embed.set_footer(text="Setup will timeout after 3 minutes of no response.")
        step1m = await ctx.send(embed=embed)
        def check(m):
            if ctx.author != m.author:
                return False
            username = m.content.split("/")[-1]
            response = requests.get(url=f"https://api.twitch.tv/kraken/users?login={username}", headers={"Accept": "application/vnd.twitchtv.v5+json", "Client-ID": self.bot.auth["client_id"]})
            json_obj = response.json()
            if len(json_obj["users"]) == 1:
                return True
        try:
            username_message = await self.bot.wait_for("message", timeout=180.0, check=check)
        except TimeoutError:
            await step1m.delete()
            return
        await username_message.delete()
        await step1m.delete()
        username = username_message.content.split("/")[-1]
        embed = Embed(
            title="Step 2 - Channel",
            description=f"Please tag a channel if you would like an alert to be sent when going live. If you do not want an alert, type 'no'",
            color=self.bot.colour
        )
        step2m = await ctx.send(embed=embed)
        def check(m):
            if ctx.author == m.author and (len(m.channel_mentions) == 1 or m.content.lower() == "no"):
                return True
        try:
            alert_channel_message = await self.bot.wait_for("message", timeout=180.0, check=check)
        except TimeoutError:
            await step2m.delete()
            return
        await alert_channel_message.delete()
        alert_role = None
        if alert_channel_message.content.lower() == "no":
            alert_channel = None
        else:
            alert_channel = alert_channel_message.channel_mentions[0]
            alert_channel_perms = alert_channel.permissions_for(ctx.guild.me)
            if alert_channel_perms.view_channel == False:
                embed = Embed(
                title="Step 2 - Channel",
                description=f"Bot is unable to see {alert_channel.mention}! Please check the bot permissions and try again.",
                color=self.bot.colour
                )
                await step2m.edit(embed=embed)
                return
            if alert_channel_perms.read_message_history == False:
                embed = Embed(
                title="Step 2 - Channel",
                description=f"Bot is unable to see message history in {alert_channel.mention}! Please check the bot permissions and try again.",
                color=self.bot.colour
                )
                await step2m.edit(embed=embed)
                return
            if alert_channel_perms.add_reactions == False:
                embed = Embed(
                title="Step 2 - Channel",
                description=f"Bot is unable to add reactions in {alert_channel.mention}! Please check the bot permissions and try again.",
                color=self.bot.colour
                )
                await step2m.edit(embed=embed)
                return
            embed = Embed(
                title="Step 2a - Role Tag",
                description=f"Please mention or provide an ID of a role you would like to to be sent with the live alert message. If you do not want an role mention, type 'no'",
                color=self.bot.colour
            )
            step2am = await ctx.send(embed=embed)
            def check(m):
                if ctx.author == m.author and (len(m.role_mentions) == 1 or m.content.lower() == "no"):
                    return True
            try:
                alert_role_message = await self.bot.wait_for("message", timeout=180.0, check=check)
            except TimeoutError:
                await step2am.delete()
                return
            
            alert_role = alert_role_message.role_mentions[0]




        username
        alert_channel.id
        alert_channel.guild.id
        alert_role.id
        with open("callbacks.json") as f:
            callbacks = json.load(f)
        if username not in callbacks.keys():
            pass #Add streamer to callbacks json and subscribe them
            
            


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