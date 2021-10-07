import aiofiles
import json
from aiohttp import ClientSession
from exceptions import *
from util.subscription import Subscription
from util.user import User, PartialUser
from util.stream import Stream
from typing import Union, List

class http:
    def __init__(self, bot, auth_file):
        self.bot = bot
        self.base = "https://api.twitch.tv/helix"
        self.oauth2_base = "https://id.twitch.tv/oauth2"
        self.storage = auth_file
        try:
            with open(auth_file) as f:
                a = json.load(f)
        except FileNotFoundError:
            raise BadAuthorization
        except json.decoder.JSONDecodeError:
            raise BadAuthorization
        try:
            self.client_id = a["client_id"]
            self.access_token = a["access_token"]
            self.callback_url = a["callback_url"]
        except KeyError:
            raise BadAuthorization
        self.headers = {"Authorization": f"Bearer {self.access_token}", "Client-Id": self.client_id}
        self.bot.add_listener(self._make_session, 'on_connect')

    async def _make_session(self):
        self.session = ClientSession()

    async def _request(self, url, method="get", **kwargs):
        response = await self.session.request(method=method, url=url, headers=self.headers, **kwargs)
        if response.status == 401: #Refresh access token
            reauth = await self.session.post(
                url=f"{self.oauth2_base}/token?client_id={self.client_id}&client_secret={self.client_secret}&grant_type=client_credentials"
            )
            if reauth.status == 401:
                raise BadAuthorization
            reauth_data = await reauth.json()
            async with aiofiles.open("config/auth.json") as f:
                auth = json.loads(await f.read())
            auth["access_token"] = reauth_data["access_token"]
            async with aiofiles.open(self.storage, "w") as f:
                await f.write(json.dumps(auth, indent=4))
            self.headers["Authorization"] = f"Bearer {reauth_data['access_token']}"
            self.access_token = reauth_data['access_token']
            response = await self.session.request(method=method, url=url, headers=self.headers, **kwargs)
            return response
        else:
            return response

    def chunks(self, lst, n):
        """Yield successive n-sized chunks from lst."""
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    async def get_users(self, users=[], user_ids=[], user_logins=[]) -> List[User]:
        queries = []
        queries += [f"id={user.id}" for user in users]
        queries += [f"id={id}" for id in user_ids]
        queries += [f"login={login}" for login in user_logins]
        users = []
        for chunk in self.chunks(queries, 100):
            join = '&'.join(chunk)
            r = await self._request(f"{self.base}/users?{join}")
            if r.status != 200:
                raise HTTPException
            json_data = (await r.json())["data"]
            for user_json in json_data:
                users += User(**user_json)
            
        return users

    async def get_user(self, user: PartialUser = None, user_id=None, user_login=None) -> User:
        if user is not None:
            r = await self._request(f"{self.base}/users?id={user.id}")
        elif user_id is not None:
            r = await self._request(f"{self.base}/users?id={user_id}")
        elif user_login is not None:
            r = await self._request(f"{self.base}/users?login={user_login}")
        else:
            raise BadRequest
        if r.status != 200:
            raise HTTPException
        j = await r.json()
        if j["data"] == []:
            return None
        json_data = j["data"][0]
        return User(**json_data)

    async def get_streams(self, user_ids=[], user_logins=[]) -> List[Stream]:
        queries = []
        queries += [f"user_id={id}" for id in user_ids]
        queries += [f"user_login={login}" for login in user_logins]
        streams = []
        if queries == []:
            raise BadRequest
        for chunk in self.chunks(queries, 20):
            join = '&'.join(chunk)
            r = await self._request(f"{self.base}/streams?{join}")
            if r.status != 200:
                raise HTTPException
            j = await r.json()
            for stream in j["data"]:
                streams.append(Stream(**stream))
            
        return streams

    async def get_stream(self, user: Union[PartialUser, User, str]) -> Union[Stream, None]:
        if type(user) in [PartialUser, User]:
            user_login = user.username
        else:
            user_login = user
        r = await self._request(f"{self.base}/streams?user_login={user_login}")
        if r.status != 200:
            raise HTTPException
        j = await r.json()
        if j["data"] == []:
            return None
        json_data = j["data"][0]
        return Stream(**json_data)

    async def get_subscription(self, id):
        r = await self._request(f"{self.base}/eventsub/subscriptions")
        rj = await r.json()
        for data in rj["data"]:
            if data["id"] == id:
                return data
        return None

    async def create_subscription(self, subscription_type: str, streamer, secret, _type="callback") -> Subscription:
        response = await self._request(f"{self.base}/eventsub/subscriptions",
                json={
                    "type": subscription_type.value,
                    "version": "1",
                    "condition": {
                        "broadcaster_user_id": str(streamer.id)
                    },
                    "transport": {
                        "method": "webhook",
                        "callback": f"{self.callback_url}/{_type}/{streamer.username.lower()}",
                        "secret": secret
                    }
                }, method="post")

        if response.status not in [202, 409]:
            raise SubscriptionError(f"There was an error subscribing to the stream online eventsub. Please try again later. Error code: {response.status}")
        j = await response.json()
        json_data = j["data"][0]
        return Subscription(**json_data)

    async def delete_subscription(self, subscription_id):
        return await self._request(f"{self.base}/eventsub/subscriptions?id={subscription_id}", method="delete")
