# Twitch Tools

A slash commands based discord bot that uses eventsub based subscriptions for fast live alerts, as well as alerts for title changes when a streamer is offline.
Also has a bad implementation of syncing bttv/ffz emotes to discord

# Setup

This setup requires you have some experience with the command line, as well as creating twitch and discord applications, python, nginx (or another reverse proxy) and mongoDB

## This was built in mind with it being ran behind a reverse proxy (nginx), I run it behind nginx myself and it is highly recommended to do the same

- Download MongoDB Community Server, install it and ensure it is running. Make sure you copy down your connection URI, you'll need it for the next step
- Clone the repo `git clone https://github.com/CataIana/twitchtools.git`
- Rename `config/exampleauth.json` to `config/auth.json` and fill in the required fields. You will need:
  * A twitch application
  * A discord bot token
  * A google api key with the youtube data API enabled
  * Your mongodb connection URI
- Install the required dependencies `sudo pip3 install -r requirements.txt`
- The webserver runs on port `18271` by default, so ensure your reverse proxy forwards your callback to that port. You can change this if necessary in the config
- Finally, run the bot with `python3 main.py` and you should be good to go

### Ensure your bot has permissions to create slash commands!

The below invite url will grant them, along with the required permissions. Make sure to replace <client_id> with your client id!
`https://discord.com/oauth2/authorize?client_id=<client_id>&permissions=224272&scope=applications.commands%20bot`

If you wish to enable the "Add to Server" button, make sure you select these permissions: Manage Channels, Read Messages/View Channels, Send Messages, Embed Links and Mention Everyone

Emote sync doesn't have an interface yet since it hasn't been fully finished. If you want to try run it, create `emote_sync.json` in the config folder. The layout per guild looks like ` { "<guild_id>": { "streamer": "<streamer_login>" } }`

Copyright &copy; 2022 CataIana, under the GNU GPLv3 License.
