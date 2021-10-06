import aiofiles
import json
from aiohttp import ClientSession
from .exceptions import *
from .subscriptions import SubscriptionType

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
        await self._validate_credentials()

    async def _validate_credentials(self):
        r = await self.session.get(f"{self.oauth2_base}/validate", headers={"Authorization": f"Bearer {self.access_token}"})
        if not r.status == 200:
            raise BadAuthorization

    async def _request(self, url, method="get", **kwargs):
        response = await self.session.request(method=method, url=url, headers=self.headers, **kwargs)
        if response.status == 401: #Refresh access token
            reauth = await self.session.post(
                url=f"{self.oauth2_base}/token?client_id={self.auth['client_id']}&client_secret={self.auth['client_secret']}&grant_type=client_credentials"
            )
            if reauth.status == 401:
                raise BadAuthorization
            reauth_data = await reauth.json()
            self.auth["access_token"] = reauth_data["access_token"]
            self.auth["refresh_token"] = reauth_data["refresh_token"]
            async with aiofiles.open(self.storage, "w") as f:
                await f.write(json.dumps(self.auth, indent=4))
            self.headers["Authorization"] = f"Bearer {self.auth['access_token']}"
            response = await self.session.request(method=method, url=url, headers=self.headers, **kwargs)
            return response
        else:
            return response

    def chunks(self, lst, n):
        """Yield successive n-sized chunks from lst."""
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    async def get_users(self, user_ids=[], user_logins=[]):
        queries = []
        queries += [f"id={id}" for id in user_ids]
        queries += [f"login={login}" for login in user_logins]
        data = []
        for chunk in self.chunks(queries, 100):
            join = '&'.join(chunk)
            r = await self._request(f"{self.base}/users?{join}")
            if r.status != 200:
                raise HTTPException
            data += (await r.json())["data"]
            
        return data

    async def get_user(self, user_id=None, user_login=None):
        if user_id is not None:
            r = await self._request(f"{self.base}/users?id={user_id}")
        elif user_login is not None:
            r = await self._request(f"{self.base}/users?login={user_id}")
        else:
            raise BadRequest
        if r.status != 200:
            raise HTTPException
        j = await r.json()
        if j["data"] == []:
            return None
        return j["data"][0]

    async def get_streams(self, user_ids=[], user_logins=[]):
        queries = []
        queries += [f"user_id={id}" for id in user_ids]
        queries += [f"user_login={login}" for login in user_logins]
        data = []
        if queries == []:
            raise BadRequest
        for chunk in self.chunks(queries, 20):
            join = '&'.join(chunk)
            r = await self._request(f"{self.base}/streams?{join}")
            if r.status != 200:
                raise HTTPException
            data += (await r.json())["data"]
            
        return data

    async def get_stream(self, user_login):
        r = await self._request(f"{self.base}/streams?user_login={user_login}")
        if r.status != 200:
            raise HTTPException
        j = await r.json()
        if j["data"] == []:
            return None
        return j["data"][0]

    async def get_subscription(self, id):
        r = await self._request(f"{self.base}/eventsub/subscriptions")
        rj = await r.json()
        for data in rj["data"]:
            if data["id"] == id:
                return data
        return None

    async def create_subscription(self, subscription_type: str, broadcaster_login, broadcaster_id, secret):
        response = await self._request(f"{self.base}/eventsub/subscriptions",
                json={
                    "type": subscription_type,
                    "version": "1",
                    "condition": {
                        "broadcaster_user_id": broadcaster_id
                    },
                    "transport": {
                        "method": "webhook",
                        "callback": f"{self.callback_url}/callback/{broadcaster_login.lower()}",
                        "secret": secret
                    }
                }, method="post")

        if response.status not in [202, 409]:
            raise SubscriptionError(f"There was an error subscribing to the stream online eventsub. Please try again later. Error code: {response.status_code}")
        j = await response.json()
        return j["data"][0]

    async def delete_subscription(self, subscription_id):
        return await self._request(f"{self.base}/eventsub/subscriptions?id={subscription_id}", method="delete")
