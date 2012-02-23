#encoding=utf-8
import sys

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

import constants
from logger import log


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
        
        self.apns = APNs(use_sandbox=self.develop,
                         cert_file=self.cert_file, key_file=self.key_file)
        
        self.server_info = server_info or {
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
        log.debug('starting a thread')
        
        self.rds = redis.Redis(**self.server_info)
        if self.job == 'push':
            self.push()
        elif self.job == 'feedback':
            self.feedback()
            
        log.debug('leaving a thread')

    def log_error(self):
        self.rds.hincrby("fail_counter", self.app_key)
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
        try:
            if real_message.get('custom', None):
                payload = Payload(alert=real_message.get('alert', None),
                                  sound=sound, badge=badge,
                                  custom=real_message['custom'])
            else:
                payload = Payload(alert=real_message.get('alert', None),
                                  sound=sound, badge=badge)
        except PayloadTooLargeError:
            payload = Payload(badge=badge)

        if self.rds.sismember('%s:%s' % (constants.INVALID_TOKENS,
                                             self.app_key),
                                  real_message['token']):
            # the token is invalid,do nothing
            return
        self.rds.hincrby("counter", self.app_key)
        log.debug('will sent a meesage to token %s', real_message['token'])
        self.apns.gateway_server.send_notification(real_message['token'],
                                                   payload)

    def resend(self, message):
        log.debug('resending')
        self.reconnect()
        self._send_message(message)

    def reconnect(self):
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
            if 'kill' == message['data']:
              break
            else:
              self.send_message(message)
            
        log.debug('i am leaving push')

    def feedback(self):
        """
        从apns获取feedback,处理无效token
        """
        while(self.alive):
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
        
        log.debug('i am leaving feedback')
