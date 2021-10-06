# Twitch Tools
A slash commands based discord bot that has eventsub based subscriptions for fast live alerts, as well as alerts for title changes when a streamer is offline.
Also has a bad implementation of syncing bttv/ffz emotes to discord

# Setup
## This assumes you have a https supported webserver to recieve eventsub callbacks. I recommend proxying with nginx if you do not currently do so.

* Clone the repo `git clone https://github.com/CataIana/twitchtools.git`
* Rename `config/exampleauth.json` to `config/auth.json` and fill in the required fields. You will need a twitch application, and a discord bot token
* Install the required dependencies `sudo pipe install --upgrade -r requirements.txt` The requirements file downloads the beta version of discord.py, but should also work just fine with the most recent full release
* The webserver runs on port `18271`, so ensure your reverse proxy forwards your callback to that port. You can change this if necessary in `webserver.py`
* Finally, run the bot with `python3 reciever_bot.py` and you should be good to go
