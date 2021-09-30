from requests import get
from json import load as j_load
from json import loads as j_loadstr
from json import dumps as j_print
import random
from string import ascii_letters
from requests import post

#Credit to GTBebbo on stackoverflow https://stackoverflow.com/questions/61288221/move-the-cursor-back-for-taking-input-python
def unix_getch():
    import termios
    import sys, tty
    def _getch():
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch.encode("utf-8")
    return _getch()

def get_input(prefix="", underscores=24, blank_char="_"):

    word = ""

    try:
        import msvcrt
        func = msvcrt.getch
    except:
        func = unix_getch

    print(prefix + (underscores - len(word)) * blank_char, end="\r", flush=True)
    # Reprint prefix to move cursor
    print(prefix, end="", flush=True)

    while True:
        ch = func()
        if ch in b"\x03":
            raise KeyboardInterrupt
        if ch in b"\x08\x7f":
            # Remove character if backspace
            word = word[:-1]
        elif ch in b"\r":
            # break if enter pressed
            break
        else:
            if len(word) == underscores:
                continue
            try:
                char = str(ch.decode("utf-8"))
            except:
                continue
            word += str(char)
        # Print `\r` to return to start of line and then print prefix, word and underscores.
        print("\r" + prefix + word + (underscores - len(word)) * blank_char, end="\r", flush=True)
        # Reprint prefix and word to move cursor
        print(prefix + word, end="", flush=True)
    print()
    return word
 
def random_string_generator(str_size):
    return "".join(random.choice(ascii_letters) for x in range(str_size))

run = True
while run:
    try:
        with open("config/callbacks.json") as f:
            callbacks = j_load(f)
    except FileNotFoundError:
        callbacks = {}
    try:
        with open("config/auth.json") as f:
            auth = j_load(f)
    except FileNotFoundError:
        raise TypeError("No Client ID file provided")
    username = get_input("Provide a twitch channel name: ")
    json_obj = get(url=f"https://api.twitch.tv/helix/users?login={username}", headers={"Client-ID": auth["client_id"], "Authorization": f"Bearer {auth['oauth']}"}).json()
    if "error" in json_obj.keys():
        raise TypeError(f"Error {json_obj['error']}: {json_obj['message']}")
    if json_obj["data"] == []:
        print("User not found")
        continue
    user = json_obj["data"][0]
    callbacks[user["name"].lower()] = {"channel_id": user["id"], "secret": random_string_generator(21)}
    with open("config/callbacks.json", "w") as f:
        f.write(j_print(callbacks, indent=4))
    print("Running subscription post")
    channel = callbacks[user["name"].lower()]
    response = post("https://api.twitch.tv/helix/eventsub/subscriptions",
                json={
                    "type": "stream.online",
                    "version": "1",
                    "condition": {
                        "broadcaster_user_id": channel["channel_id"]
                    },
                    "transport": {
                        "method": "webhook",
                        "callback": f"{auth['callback_url']}/callback/{user['login'].lower()}",
                        "secret": channel["secret"]
                    }
                }, headers={"Authorization": f"Bearer {auth['oauth']}", "Client-ID": auth["client_id"], "Content-Type": "application/json"})
    response2 = post("https://api.twitch.tv/helix/eventsub/subscriptions",
                json={
                    "type": "stream.offline",
                    "version": "1",
                    "condition": {
                        "broadcaster_user_id": channel["channel_id"]
                    },
                    "transport": {
                        "method": "webhook",
                        "callback": f"{auth['callback_url']}/callback/{user['login'].lower()}",
                        "secret": channel["secret"]
                    }
                }, headers={"Authorization": f"Bearer {auth['oauth']}", "Client-ID": auth["client_id"], "Content-Type": "application/json"})
    r1 = response.json()
    r2 = response2.json()
    print(f"Response for {callbacks[user['login']]} {response.status_code}: {response}")
    print(f'IDs Online: {r1["data"][0]["id"]} Offline: {r2["data"][0]["id"]}')
    print("Done")
