#encoding=utf-8

import redis
from apnsagent import constants
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

    def push(self, token=None, alert=None, badge=None,
             sound=None, custom=None):
        """向推送服务发起推送消息。
        Arguments:
        - `token`:
        - `alert`:
        - `badge`:
        - `sound`:
        - `custom`:
        """
        assert token is not None, 'token is reqiured'

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
