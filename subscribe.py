from requests import post
import schedule
from time import sleep
import json


class Subscriber():
    def __init__(self):
        schedule.every(7).days.at("10:00").do(self.resubscribe)

    def resubscribe(self):
        print("Resubscribing...")
        try:
            with open("callbacks.json") as f:
                callbacks = json.load(f)
        except FileNotFoundError:
            raise TypeError("Cannot locate callback settings file")
        try:
            with open("auth.json") as f:
                auth = json.load(f)
        except FileNotFoundError:
            raise TypeError("Cannot find authorization file ")
        for channel_name, channel in callbacks.items():
            response = post("https://api.twitch.tv/helix/webhooks/hub",
                data={
                    "hub.callback": f"https://twitch-callback.catalana.dev/callback/{channel_name.lower()}",
                    "hub.mode": "subscribe",
                    "hub.topic": f"https://api.twitch.tv/helix/streams?user_id={channel['channel_id']}",
                    "hub.lease_seconds": "691200",
                    "hub.secret": channel["secret"]
                }, headers={"Authorization": f"Bearer {auth['oauth']}", "Client-Id": auth["client_id"]})
            print(f"Response for {channel_name}: {response}")
            if len(callbacks.items()) > 1:
                sleep(2)
        print("Done")

    def run(self):
        while True:
            schedule.run_pending()
            sleep(1)


s = Subscriber()
#s.resubscribe()
s.run()
