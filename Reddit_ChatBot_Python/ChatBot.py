from .WebSockClient import WebSockClient
# from .Utils.ChatMedia import ChatMedia
import requests
import pickle
from .RedditAuthentication import TokenAuth, PasswordAuth
from websocket import WebSocketConnectionClosedException


class ChatBot:
    REDDIT_OAUTH_HOST = "https://oauth.reddit.com"
    REDDIT_SENDBIRD_HOST = "https://s.reddit.com"

    def __init__(self, authentication, store_session=True, **kwargs):
        assert isinstance(authentication, (TokenAuth, PasswordAuth)), "Wrong Authentication type"
        self.headers = {'User-Agent': "Reddit/Version 2020.41.1/Build 296539/Android 11"}
        self.authentication = authentication
        if store_session:
            pkl_n = authentication.token if isinstance(authentication, TokenAuth) else authentication.reddit_username
            sb_access_token, user_id = self._load_session(pkl_n)
        else:
            sb_access_token, user_id = self._get_new_session()

        self.WebSocketClient = self._init_websockclient(sb_access_token=sb_access_token, user_id=user_id, **kwargs)

        # if with_chat_media:  # this is untested
        #     self.ChatMedia = ChatMedia(key=sb_access_token, ai=self._SB_ai, reddit_api_token=reddit_api_token)

    def _init_websockclient(self, sb_access_token, user_id, **kwargs):
        return WebSockClient(access_token=sb_access_token, user_id=user_id, **kwargs)

    def get_chatroom_name_id_pairs(self):
        return self.WebSocketClient.channelid_sub_pairs

    def after_message_hook(self, frame_type='MESG'):
        def after_frame_hook(func):
            def hook(resp):
                if resp.type_f == frame_type:
                    func(resp)
            self.WebSocketClient.after_message_hooks.append(hook)
        return after_frame_hook

    def set_respond_hook(self, input_, response, limited_to_users=None, lower_the_input=False, exclude_itself=True,
                         must_be_equal=True, limited_to_channels=None):

        if limited_to_users is not None and isinstance(limited_to_channels, str):
            limited_to_users = [limited_to_users]
        elif limited_to_users is None:
            limited_to_users = []
        if limited_to_channels is not None and isinstance(limited_to_channels, str):
            limited_to_channels = [limited_to_channels]
        elif limited_to_channels is None:
            limited_to_channels = []

        try:
            response.format(nickname="")
        except KeyError as e:
            raise Exception("You need to set a {nickname} key in welcome message!") from e

        def hook(resp):
            if resp.type_f == "MESG":
                sent_message = resp.message.lower() if lower_the_input else resp.message
                if (resp.user.name in limited_to_users or not bool(limited_to_users)) \
                        and (exclude_itself and resp.user.name != self.WebSocketClient.own_name) \
                        and ((must_be_equal and sent_message == input_) or (not must_be_equal and input_ in sent_message)) \
                        and (self.WebSocketClient.channelid_sub_pairs.get(resp.channel_url) in limited_to_channels or not bool(limited_to_channels)):
                    response_prepped = response.format(nickname=resp.user.name)
                    self.WebSocketClient.ws_send_message(response_prepped, resp.channel_url)
                    return True

        self.WebSocketClient.after_message_hooks.append(hook)

    def set_welcome_message(self, message, limited_to_channels=None):
        try:
            message.format(nickname="", inviter="")
        except KeyError as e:
            raise Exception("Keys should be {nickname} and {inviter}") from e

        if limited_to_channels is not None and isinstance(limited_to_channels, str):
            limited_to_channels = [limited_to_channels]
        elif limited_to_channels is None:
            limited_to_channels = []

        def hook(resp):
            if resp.type_f == "SYEV" and (self.WebSocketClient.channelid_sub_pairs.get(resp.channel_url) in limited_to_channels or not bool(limited_to_channels)):
                try:
                    nickname = resp.data.users[0].nickname
                    inviter = resp.data.users[0].inviter.nickname
                except (AttributeError, IndexError):
                    return
                response_prepped = message.format(nickname=nickname, inviter=inviter)
                self.WebSocketClient.ws_send_snoomoji(response_prepped, resp.channel_url)
                return True

        self.WebSocketClient.after_message_hooks.append(hook)

    def set_farewell_message(self, message, limited_to_channels=None):
        try:
            message.format(nickname="")
        except KeyError as e:
            raise Exception("Key should be {nickname}") from e

        if limited_to_channels is not None and isinstance(limited_to_channels, str):
            limited_to_channels = [limited_to_channels]
        elif limited_to_channels is None:
            limited_to_channels = []

        def hook(resp):
            if resp.type_f == "SYEV" and (self.WebSocketClient.channelid_sub_pairs.get(resp.channel_url) in limited_to_channels or not bool(limited_to_channels)):
                try:
                    dispm = resp.channel.disappearing_message
                    nickname = resp.data.nickname
                except AttributeError:
                    return
                response_prepped = message.format(nickname=nickname)
                self.WebSocketClient.ws_send_message(response_prepped, resp.channel_url)
                return True

        self.WebSocketClient.after_message_hooks.append(hook)

    def send_message(self, text, channel_url):
        self.WebSocketClient.ws_send_message(text, channel_url)

    def send_snoomoji(self, snoomoji, channel_url):
        self.WebSocketClient.ws_send_snoomoji(snoomoji, channel_url)

    def run_4ever(self, auto_reconnect=True, max_retries=100):
        for _ in range(max_retries):
            self.WebSocketClient.ws.run_forever(ping_interval=15, ping_timeout=5)
            if auto_reconnect and isinstance(self.WebSocketClient.last_err, WebSocketConnectionClosedException):
                self.WebSocketClient.logger.info('Auto Reconnecting...')
                continue
            else:
                break

    def _load_session(self, pkl_name):
        try:
            session_store_f = open(f'{pkl_name}-stored.pkl', 'rb')
            sb_access_token = pickle.load(session_store_f)
            user_id = pickle.load(session_store_f)
            print("loading from session goes brrr")
        except FileNotFoundError:
            session_store_f = open(f'{pkl_name}-stored.pkl', 'wb+')
            sb_access_token, user_id = self._get_new_session()
            pickle.dump(sb_access_token, session_store_f)
            pickle.dump(user_id, session_store_f)
        finally:
            session_store_f.close()

        return sb_access_token, user_id

    def _get_new_session(self):
        reddit_api_token = self.authentication.authenticate()
        self.headers.update({'Authorization': f'Bearer {reddit_api_token}'})
        sb_access_token = self._get_sendbird_access_token()
        user_id = self._get_user_id()
        return sb_access_token, user_id

    def _get_sendbird_access_token(self):
        response = requests.get(f'{ChatBot.REDDIT_SENDBIRD_HOST}/api/v1/sendbird/me', headers=self.headers)
        response.raise_for_status()
        return response.json()['sb_access_token']

    def _get_user_id(self):
        response = requests.get(f'{ChatBot.REDDIT_OAUTH_HOST}/api/v1/me.json', headers=self.headers)
        response.raise_for_status()
        return 't2_' + response.json()['id']

    #  LEGACY STUFF
    # def join_channel(self, sub, channel_url):
    #     if channel_url.startswith("sendbird_group_channel_"):
    #         channel_url_ = channel_url
    #     else:
    #         channel_url_ = "sendbird_group_channel_" + channel_url
    #     sub_id = self._get_sub_id(sub)
    #     data = f'{{"channel_url":"{channel_url_}","subreddit":"{sub_id}"}}'
    #     resp = requests.post(f'{ChatBot.REDDIT_SENDBIRD_HOST}/api/v1/sendbird/join', headers=self.headers, data=data)
    #     return resp.text

    # def get_sendbird_channel_urls(self, sub_name):
    #     sub_id = self._get_sub_id(sub_name)
    #     response = requests.get(f'{ChatBot.REDDIT_SENDBIRD_HOST}/api/v1/subreddit/{sub_id}/channels', headers=self.headers)
    #     response.raise_for_status()
    #     try:
    #         rooms = response.json().get('rooms')
    #         for room in rooms:
    #             yield room.get('url')
    #     except (KeyError, IndexError):
    #         raise Exception('Sub doesnt have any rooms')

    # def _get_sub_id(self, sub_name):
    #     response = requests.get(f'{ChatBot.REDDIT_OAUTH_HOST}/r/{sub_name}/about.json', headers=self.headers)
    #     response.raise_for_status()
    #     sub_id = response.json().get('data').get('name')
    #     if sub_id is None:
    #         raise Exception('Wrong subreddit name')
    #     return sub_id
