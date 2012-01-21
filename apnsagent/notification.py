#encoding=utf-8
import sys
import re
import traceback
try:
    import simplejson
except:
    from django.utils import simplejson
from apns import APNs, Payload
from apns import PayloadTooLargeError
from ssl import SSLError
import socket
import redis
import time
from datetime import datetime

from apnsagent import constants
from apnsagent.logger import log


class SafePayload(Payload):
    """为了手动检查推送信息的长度，自制一个安全的Payload
    """
    def __init__(self, alert=None, badge=None, sound=None, custom={}):
        self.alert = alert
        self.badge = badge
        self.sound = sound
        self.custom = custom

    def as_payload(self):
        try:
            return Payload(self.alert, self.badge, self.sound, self.custom)
        except:
            log.error('payload still Tool long')


class Notifier(object):
    def __init__(self, job='push', develop=False, app_key=None,
                 cer_file=None, key_file=None, server_info=None):
        """
        job = push | feedback
        develop,是否使用sandbox服务器，调试时设为True
        app_key,使用推送服务的应用唯一标识，格式建议为com.company.appname
        cert_file,该应用的推送证书，PEM格式
        key_file,该应用的密钥，PEM格式，要求去掉passphase
        """
        self.job = job
        self.develop = develop
        self.app_key = app_key
        self.cert_file = cer_file
        self.key_file = key_file

        self.alive = True

        self.last_sent_time = datetime.now()
        self.trim_alerts = {}
        self.apns = APNs(use_sandbox=self.develop,
                         cert_file=self.cert_file, key_file=self.key_file)
        if server_info:
            self.server_info = server_info
        else:
            self.server_info = {
                'host': '127.0.0.1',
                'post': 6379,
                'db': 0,
                'password': ''
                }

    def run(self):
        """
        - 监听redis队列，发送push消息
        - 从apns获取feedback service，处理无效token
        """
        self.rds = redis.Redis(**self.server_info)
        if self.job == 'push':
            self.push()
        elif self.job == 'feedback':
            self.feedback()

    def log_error(self):
        log.error('message push fail')
        type, value, tb = sys.exc_info()
        error_message = traceback.format_exception(type, value, tb)
        log.debug(type)
        log.error(error_message)

    def send_message(self, message):
        """
        发送消息，如果发生异常失败，重新连接再试一次，再失败则丢失
        """
        log.debug('get a message from channel')
        log.debug(message)
        try:
            if message['type'] != 'message':
                return
            self._send_message(message)
        except SSLError:
            self.log_error()
            self.resend(message)
        except socket.error:
            self.log_error()
            self.resend(message)
        except:
            self.log_error()

    def _send_message(self, message):
        real_message = simplejson.loads(message['data'])
        badge = real_message.get('badge', None)
        sound = real_message.get('sound', None)
        alert = real_message.get('alert', None)
        custom = real_message.get('custom', {})

        if self.rds.sismember('%s:%s' % (constants.INVALID_TOKENS,
                                         self.app_key),
                              real_message['token']):
            # the token is invalid,do nothing
            return
        try:
            payload = Payload(sound=sound, badge=badge, alert=alert,
                              custom=custom)

        except PayloadTooLargeError:
            # 在内存保留100条缩短后消息，避免批量发送时，每条都要缩短的损耗
            if not alert:
                log.error('push meta data too long to trim, discard')
                payload = None
            if isinstance(alert, dict):
                log.error('payload too long to trim, discard')
                payload = None

            log.debug('try to trime large alert')
            payload = SafePayload(sound=sound, badge=badge, alert=alert,
                                  custom=custom)
            l_payload = len(payload.json())
            l_alert = len(alert.encode('unicode_escape'))
            l_allow = 256 - (l_payload - l_alert) - 3  # 允许提示长度

            ec_alert = alert.encode('unicode_escape')
            t_alert = re.sub(r'([^\\])\\(u|$)[0-9a-f]{0,3}$', r'\1',
                             ec_alert[:l_allow])
            alert = t_alert.decode('unicode_escape') + u'...'

            log.debug('payload is : %s' % alert)

            payload.alert = alert
            log.debug('how long dest it after trim %d' % len(payload.json()))
            payload = payload.as_payload()

        if not payload:
            return

        log.debug('will sent a meesage to token %s', real_message['token'])
        now = datetime.now()
        if (now - self.last_sent_time).seconds > 300:
            log.debug('idle for a long time , reconnect now.')
            self.reconnect()
        self.apns.gateway_server.send_notification(real_message['token'],
                                                   payload)
        self.last_sent_time = datetime.now()
        self.rds.hincrby("counter", self.app_key)

    def resend(self, message):
        log.debug('resending')
        self.reconnect()
        self._send_message(message)

    def reconnect(self):
        # TODO disconnect and create a new connection
        self.apns = APNs(use_sandbox=self.develop,
                         cert_file=self.cert_file, key_file=self.key_file)

    def push(self):
        """
        监听消息队列，获取推送请求，推送消息到客户端
        """
        #先处理fallback里面留下来的消息，理论上那里的数据不会很多
        fallback = constants.PUSH_JOB_FALLBACK_DEV \
                  if self.develop else \
                  constants.PUSH_JOB_FALLBACK
        channel = constants.PUSH_JOB_CHANNEL_DEV \
                  if self.develop else \
                  constants.PUSH_JOB_CHANNEL

        log.debug('handle fallback messages')
        old_msg = self.rds.spop('%s:%s' % (fallback, self.app_key))
        while(old_msg):
            log.debug('handle message:%s' % old_msg)
            try:
                simplejson.loads(old_msg)
                self.send_message({'type': 'message', 'data': old_msg})
            except:
                log.debug('message is not a json object')
            finally:
                old_msg = self.rds.spop('%s:%s' % (fallback, self.app_key))

        # 再订阅消息队列
        pubsub = self.rds.pubsub()
        pubsub.subscribe('%s:%s' % (channel, self.app_key))
        log.debug('subscribe push job channel successfully')
        redis_channel = pubsub.listen()
        for message in redis_channel:
            if not self.alive:
                break
            self.send_message(message)

    def feedback(self):
        """
        从apns获取feedback,处理无效token
        """
        while(True):
            try:
                for (token, fail_time) in self.apns.feedback_server.items():
                    log.debug('push message fail to send to %s.' % token)
                    self.rds.sadd('%s:%s' % (constants.INVALID_TOKENS,
                                             self.app_key),
                                  token)
            except:
                self.log_error()
                self.reconnect()
            time.sleep(10)
