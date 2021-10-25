# Twitch Tools
A slash commands based discord bot that uses eventsub based subscriptions for fast live alerts, as well as alerts for title changes when a streamer is offline.
Also has a bad implementation of syncing bttv/ffz emotes to discord

# Setup
## This was built in mind with it being ran behind a reverse proxy (nginx), I run it behind nginx myself and it is highly recommended to do the same

* Clone the repo `git clone https://github.com/CataIana/twitchtools.git`
* Rename `config/exampleauth.json` to `config/auth.json` and fill in the required fields. You will need a twitch application, and a discord bot token
* Install the required dependencies `sudo pip3 install -r requirements.txt` The requirements file downloads the beta version of discord.py, but should also work just fine with discord.py 1.7.3
* The webserver runs on port `18271`, so ensure your reverse proxy forwards your callback to that port. You can change this if necessary in `webserver.py`
* Finally, run the bot with `python3 main.py` and you should be good to go
### Ensure your bot has permissions to create slash commands!
The below invite url will grant them, along with the required permissions. Make sure to replace <client_id> with your client id!
`https://discord.com/oauth2/authorize?client_id=<client_id>&permissions=224272&scope=applications.commands%20bot`

Emote sync doesn't have an interface yet since I haven't fully finished it. If you want to try run it, create `emote_sync.json` in the config folder. The layout per guild looks like ```
{
  "<guild_id>": 
  { 
    "streamer": "<streamer_login>" 
    }  
}```
