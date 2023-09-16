# Twitch Tools

## Features

* Eventsub based stream online/offline notifications
* Eventsub based offline title/category change notifications
* Catchup for missed notifications
* Temporary and persistent live channels 
* Customisable role mentions, including @everyone and no role
* Game history for past stream messages
* Live title and game updates for notifications
* Stream length logging for individual games
* Server specific manager roles to allow a role access to modify setup
* Youtube livestream support
* Youtube premiere support (toggleable)
* Colour indictions of whether a stream is a YouTube or Twitch stream
* Alert cooldown and message reuse for stream crashes


# Setup

## Requirements

* Python 3.9 or higher
* MongoDB
* Git
* A domain that you control (Must support SSL)
* Basic knowledge of python
* Some command line experience
* Knowledge of how to create twitch and discord developer applications
* Knowledge of how to use nginx or another reverse proxy


## Setup instructions

- Download MongoDB Community Server, install it and ensure it is running. Make sure you copy your [connection string](https://www.mongodb.com/docs/manual/reference/connection-string/)
- Clone the repo `git clone https://github.com/CataIana/twitchtools.git`
- Rename `config/exampleauth.json` to `config/auth.json` and fill in the required fields. You will need:
  * A twitch application
  * A discord bot token
  * A google API key with the YouTube data API enabled
  * Your mongodb connection string
  * Your callback URI (You must set this up in your domain DNS settings)
- Install the required dependencies `pip3 install -r requirements.txt`
- The webserver runs on port `18271` by default, so ensure your reverse proxy forwards your callback to that port. You can change this if necessary in the config
- Finally, run the bot with `python3 main.py` and you should be good to go



### Ensure your bot has permissions to create slash commands!

The below invite url will grant them, along with the required permissions. Make sure to replace <client_id> with your discord bot client id!
`https://discord.com/oauth2/authorize?client_id=<client_id>&permissions=224272&scope=applications.commands%20bot`

If you wish to enable the "Add to Server" button, make sure you select these permissions: Manage Channels, Read Messages/View Channels, Send Messages, Embed Links and Mention Everyone

Copyright &copy; 2023 CataIana, under the GNU GPLv3 License.
