#encoding=utf-8

import redis
import constants
import socket
import time
try:
    import simplejson
except:
    from django.utils import simplejson


class PushClient(object):
    """推送服务的客户端，负责把消息扔进推送主队列即可。
    """

    def __init__(self, app_key, server_info={}):
        """建立推送客户端。
        - app_key 客户端的app_key,前期为局域网内部的服务，暂不作有效性检测。
        - server_info 连接推送服务后端的信息
        """
        self.app_key = app_key
        self.redis = redis.Redis(**server_info)
        self._socket = None

    def register_token(self, token, user_id=None, develop=False):
        """添加Token到服务器，并标识是何种类型的，测试或生产
        Arguments:
        - `self`:
        - `token`:
        - `user_id`: token所对应的用户名,以后支持一个用户名对应多台机器
        - `develop`: 该token对应的推送环境，测试或生产
        """
        if develop:
            self.redis.sadd('%s:%s' % (constants.DEBUG_TOKENS, self.app_key),
                            token)
        else:
            self.redis.srem('%s:%s' % (constants.DEBUG_TOKENS, self.app_key),
                            token)
        # 检查token是否在黑名单里，如果在，则从黑名释放出来
        if self.redis.sismember('%s:%s' % (constants.INVALID_TOKENS,
                                           self.app_key), token):
            self.redis.srem('%s:%s' % (constants.INVALID_TOKENS,
                                       self.app_key), token)
        #TODO 为用户ID和token加上关联。

    def get_target(self, token):
        """根据Token找到需要推送的目标队列
        Arguments:
        - `self`:
        - `token`:
        """
        is_develop = self.redis.sismember('%s:%s' % (constants.DEBUG_TOKENS,
                                                     self.app_key), token)
        return ('%s:%s' % (constants.PUSH_JOB_CHANNEL_DEV, self.app_key),
                '%s:%s' % (constants.PUSH_JOB_FALLBACK_DEV, self.app_key)) \
                if is_develop else \
                ('%s:%s' % (constants.PUSH_JOB_CHANNEL, self.app_key),
                '%s:%s' % (constants.PUSH_JOB_FALLBACK, self.app_key))

    def sent_message_count(self):
        return self.redis.hget("counter", self.app_key)

    def debug_tokens(self):
        return self.redis.smembers('%s:%s' % (constants.DEBUG_TOKENS,
                                              self.app_key))

    def invalid_tokens(self):
        return self.redis.smembers('%s:%s' % (constants.INVALID_TOKENS,
                                              self.app_key))

    def push(self, token=None, alert=None, badge=None,
             sound=None, custom=None, enhance=False):
        """向推送服务发起推送消息。
        Arguments:
        - `token`:
        - `alert`:
        - `badge`:
        - `sound`:
        - `custom`:
        """
        assert token is not None, 'token is reqiured'

        if enhance:
            self.epush(token, alert, badge, sound, custom)
            return
        channel, fallback_set = self.get_target(token)

        d = {'token': token}
        if alert:
            d['alert'] = alert
        if badge:
            d['badge'] = badge
        if sound:
            d['sound'] = sound
        if custom:
            d['custom'] = custom
        payload = simplejson.dumps(d)
        clients = self.redis.publish(channel, payload)
        if not clients:
            self.redis.sadd(fallback_set, payload)  # TODO 加上超时

    def push_batch(self, tokens, alert):
        """push message in batch
        """
        token = tokens[0]
        channel, fallback_set = self.get_target(token)

        for tk in tokens:
            d = {'token': tk}
            if alert:
                d['alert'] = alert
            payload = simplejson.dumps(d)

            clients = self.redis.publish(channel, payload)
            if not clients:
                self.redis.sadd(fallback_set, payload)  # TODO 加上超时

    def stop(self):
        self.redis.publish("app_watcher",
                           simplejson.dumps({'op': 'stop',
                                             'app_key': self.app_key}))

    def start(self):
        self.redis.publish("app_watcher",
                           simplejson.dumps({'op': 'start',
                                             'app_key': self.app_key}))

    def valid(self):
        """valid app_key
        """
        pass

    ################# enhanced push #################

    def _get_enhance_server(self, token):
        """返回增强推送服务的信息
        """
        is_develop = self.redis.sismember('%s:%s' % (constants.DEBUG_TOKENS,
                                                     self.app_key), token)
        port = self.redis.hget('ENHANCE_PORT',
                               ':'.join((self.app_key,
                                         'dev' if is_develop else 'pro')
                                        )
                               )
        return 'localhost', int(port)

    def epush(self, token=None, alert=None, badge=None,
             sound=None, custom=None):
        """使用Ehanced协议推送，使用socket连接池，
        """
        if not self._socket:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                self._socket.connect(self._get_enhance_server(token))
            except socket.error, e:
                raise e

        try:
            d = {'token': token}
            if alert:
                d['alert'] = alert
            if badge:
                d['badge'] = badge
            if sound:
                d['sound'] = sound
            if custom:
                d['custom'] = custom
            data = simplejson.dumps(d)
            self._socket.send(data)
        except socket.error:
            print 'socket error when send message'
            time.sleep(1)
            self._socket.close()
            self._socket = None
            self.epush(token, alert, badge, sound, custom)
        except:
            return
