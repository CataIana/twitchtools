from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, List, Optional, Union

from aiohttp import ClientSession
from aiohttp.client_reqrep import ClientResponse

from .enums import AlertOrigin, AlertType, SubscriptionType
from .exceptions import *
from .stream import Stream
from .subscription import Subscription, SubscriptionEvent, TitleEvent
from .user import PartialUser, User
from .video import Video

if TYPE_CHECKING:
    from main import TwitchCallBackBot


class http_twitch:
    def __init__(self, bot, client_id, client_secret, callback_url, **kwargs):
        self.bot: TwitchCallBackBot = bot
        self.base = "https://api.twitch.tv/helix"
        self.oauth2_base = "https://id.twitch.tv/oauth2"
        try:
            self.client_id: str = client_id
            self.client_secret: str = client_secret
            self.access_token: str = None
            self.callback_url: str = callback_url
        except KeyError:
            raise BadAuthorization
        self.bot.add_listener(self._make_session, 'on_connect')
        self.bot.add_listener(self._fetch_access_token, 'on_connect')

    async def _fetch_access_token(self):
        await self.bot.wait_until_db_ready()
        self.access_token = await self.bot.db.get_access_token()

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}", "Client-Id": self.client_id}

    async def _make_session(self):
        self.session: ClientSession = ClientSession()

    async def close_session(self):
        if not self.session.closed:
            await self.session.close()

    async def _request(self, url, method="get", **kwargs):
        response = await self.session.request(method=method, url=url, headers=self.headers, **kwargs)
        if response.status == 401:  # Refresh access token
            reauth = await self.session.post(url=f"{self.oauth2_base}/token", data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials"
            })
            if reauth.status in [401, 400]:
                reauth_data = await reauth.json()
                raise BadAuthorization(reauth_data["message"])
            reauth_data = await reauth.json()
            try:
                self.access_token = reauth_data['access_token']
            except KeyError:
                raise BadAuthorization(f"Error obtaining access token: Status code {reauth.status}. {reauth_data.get('message', 'No message available')}")
            await self.bot.db.write_access_token(self.access_token)
            response = await self.session.request(method=method, url=url, headers=self.headers, **kwargs)
        return response

    def chunks(self, lst, n):
        """Yield successive n-sized chunks from lst."""
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    async def get_users(self, users: List[PartialUser] = [], user_ids: List[int] = [], user_logins: List[str] = []) -> List[User]:
        queries = []
        queries += [f"id={user.id}" for user in users]
        queries += [f"id={id}" for id in user_ids]
        queries += [f"login={login}" for login in user_logins]
        users = []
        for chunk in self.chunks(queries, 100):
            join = '&'.join(chunk)
            r = await self._request(f"{self.base}/users?{join}")
            json_data = (await r.json())["data"]
            for user_json in json_data:
                users += User(**user_json)

        return users

    async def get_user(self, user: PartialUser = None, user_id: int = None, user_login: str = None) -> Optional[User]:
        if user is not None:
            r = await self._request(f"{self.base}/users?id={user.id}")
        elif user_id is not None:
            r = await self._request(f"{self.base}/users?id={user_id}")
        elif user_login is not None:
            r = await self._request(f"{self.base}/users?login={user_login}")
        else:
            raise BadRequest
        j = await r.json()
        if j.get("data", []) == []:
            return None
        json_data = j["data"][0]
        return User(**json_data)
    
    async def get_user_follow_count(self, user: PartialUser = None, user_id: int = None) -> Optional[str]:
        if user is not None:
            r = await self._request(f"{self.base}/users/follows?to_id={user.id}")
        elif user_id is not None:
            r = await self._request(f"{self.base}/users/follows?to_id={user_id}")
        else:
            raise BadRequest
        j = await r.json()
        return j.get("total", None)

    async def get_streams(self, users: List[Union[User, PartialUser]] = [], user_ids: List[int] = [], user_logins: List[str] = [], origin: AlertOrigin = AlertOrigin.unavailable) -> List[Stream]:
        queries = []
        queries += [f"user_id={user.id}" for user in users]
        queries += [f"user_id={id}" for id in user_ids]
        queries += [f"user_login={login}" for login in user_logins]
        streams = []
        if queries == []:
            raise BadRequest
        for chunk in self.chunks(queries, 20):
            join = '&'.join(chunk)
            r = await self._request(f"{self.base}/streams?{join}")
            j = await r.json()
            for stream in j.get("data", []):
                s = Stream(**stream)
                s.origin = origin
                streams.append(s)
        return streams

    async def get_stream(self, user: Union[PartialUser, User], origin: AlertOrigin = AlertOrigin.unavailable) -> Union[Stream, None]:
        r = await self._request(f"{self.base}/streams?user_login={user}")
        j = await r.json()
        if j.get("data", []) == []:
            return None
        json_data = j["data"][0]
        s = Stream(**json_data)
        s.origin = origin
        return s

    async def get_subscription(self, id: str) -> Union[Subscription, None]:
        r = await self._request(f"{self.base}/eventsub/subscriptions")
        rj = await r.json()
        for sub in rj.get("data", []):
            if sub["id"] == id:
                return Subscription(**sub)
        return None

    async def get_subscriptions(self) -> List[Subscription]:
        r = await self._request(f"{self.base}/eventsub/subscriptions")
        rj = await r.json()
        subs = []
        for sub in rj.get("data", []):
            subs.append(Subscription(**sub))
        return subs

    def get_event(self, data) -> Optional[SubscriptionEvent]:
        event_type = SubscriptionType(data["subscription"]["type"])
        if event_type == SubscriptionType.CHANNEL_UPDATE:
            return TitleEvent(**data)
        return None

    async def create_subscription(self, subscription_type: SubscriptionType, streamer: Union[User, PartialUser], secret: str, alert_type: AlertType = AlertType.status) -> Subscription:
        response = await self._request(f"{self.base}/eventsub/subscriptions",
                                       json={
                                           "type": subscription_type.value,
                                           "version": "1",
                                           "condition": {
                                               "broadcaster_user_id": str(streamer.id)
                                           },
                                           "transport": {
                                               "method": "webhook",
                                               "callback": f"{self.callback_url}/{alert_type.value}/{streamer.user_id}",
                                               "secret": secret
                                           }
                                       }, method="post")

        if response.status not in [202, 409]:
            raise SubscriptionError(
                f"There was an error subscribing to the stream online eventsub. Please try again later. Error code: {response.status}")
        j = await response.json()
        try:
            json_data = j["data"][0]
        except KeyError:
            self.bot.log.error(f"Subscription Create Error: {str(j)}")
            raise SubscriptionError(
                f"There was an error creating the {subscription_type.value} subscription: `{str(j)}`")
        subscription = Subscription(**json_data)

        # Wait for subscription confirmation
        def check(sub_id):
            return sub_id == subscription.id
        try:
            await self.bot.wait_for("subscription_confirmation", check=check, timeout=8)
        except asyncio.TimeoutError:
            await self.delete_subscription(subscription.id)
            raise SubscriptionError(
                "Did not receive subscription confirmation! Please try again later")

        return subscription

    async def delete_subscription(self, subscription: Union[Subscription, str]) -> ClientResponse:
        if isinstance(subscription, Subscription):
            subscription = subscription.id
        return await self._request(f"{self.base}/eventsub/subscriptions?id={subscription}", method="delete")

    async def get_videos(self, user: Union[User, PartialUser]) -> list[Video]:
        r = await self._request(f"{self.base}/videos?user_id={user.id}")
        rj = await r.json()
        vids = []
        for vid in rj.get("data", []):
            vids.append(Video(**vid))
        return vids

    async def get_video(self, video_id: int) -> Optional[Video]:
        r = await self._request(f"{self.base}/videos?id={video_id}")
        rj = await r.json()
        for vid in rj.get("data", []):
            return Video(**vid)
        return None

    async def get_video_from_stream_id(self, user: Union[User, PartialUser], stream_id: int) -> Optional[Video]:
        r = await self._request(f"{self.base}/videos?user_id={user.id}")
        rj = await r.json()
        for vid in rj.get("data", []):
            if int(vid['stream_id']) == stream_id:
                return Video(**vid)
        return None
