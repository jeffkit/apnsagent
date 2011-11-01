#encoding=utf-8
import os
import sys

if os.getcwd() not in sys.path:
    sys.path.append(os.getcwd())

import traceback
from apnsagent import settings
from django.utils import simplejson
from django.core.mail import send_mail
from apns import APNs,Payload
from apns import PayloadTooLargeError
from ssl import SSLError
import socket
import redis
import time
from logger import log



class Notifier(object):
    def __init__(self, job='push', develop=False, app_key=None,
                 cer_file=None, key_file=None):
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

        self.apns = APNs(use_sandbox=self.develop,
                         cert_file=self.cert_file, key_file=self.key_file)

    def run(self):
        """
        - 监听redis队列，发送push消息
        - 从apns获取feedback service，处理无效token
        """
        if self.job == 'push':
            self.rds = redis.Redis(host=settings.REDIS_HOST,
                                   port=settings.REDIS_PORT,
                                   db=settings.REDIS_DATABASE)
            self.push()
        elif self.job == 'feedback':
            self.feedback()

    def log_error(self):
        log.error('message push fail')
        type,value,tb = sys.exc_info()
        error_message = traceback.format_exception(type,value,tb)
        log.debug(type)
        log.error(error_message)
        send_mail('message push fail by %s exception' % str(type),
                  error_message, 'techparty.org@gmail.com', ['bbmyth@gmail.com'],
                  fail_silently=True)

    def send_message(self,message):
        """
        发送消息，如果发生异常失败，重新连接再试一次，再失败则丢失
        """
        log.debug('get a message from channel')
        log.debug(message)
        try:
            if message['type'] != 'message':return
            self._send_message(message)
        except SSLError:
            self.log_error()
            self.resend(message)
        except socket.error:
            self.log_error()
            self.resend(message)
        except:
            self.log_error()

    def _send_message(self,message):
        real_message = simplejson.loads(message['data'])
        badge = real_message.get('badge', None)
        sound = real_message.get('sound', None)
        try:
            if real_message.get('custom',None):
                payload = Payload(alert=real_message['alert'], sound=sound,
                                  custom=real_message['custom'],badge=badge)
            else:
                payload = Payload(alert=real_message['alert'],
                                  sound=sound, badge=badge)
        except PayloadTooLargeError, e:
            payload = Payload(badge=badge)
        
        log.debug('will sent a meesage to token %s',real_message['token'])
        self.apns.gateway_server.send_notification(real_message['token'],payload)

    def resend(self,message):
        log.debug('resending')
        self.reconnect()
        self._send_message(message)


    def reconnect(self):
        self.apns = APNs(use_sandbox=self.develop, cert_file=self.cert_file, key_file=self.key_file)

    def push(self):
        """
        监听消息队列，获取推送请求，推送消息到客户端
        """
        #先处理fallback里面留下来的消息，理论上那里的数据不会很多
        fallback = settings.PUSH_JOB_FALLBACK_DEV \
                  if self.develop else \
                  settings.PUSH_JOB_FALLBACK
        channel = settings.PUSH_JOB_CHANNEL_DEV \
                  if self.develop else \
                  settings.PUSH_JOB_CHANNEL
        
        log.debug('handle fallback messages')
        old_msg = self.rds.spop('%s:%s' % (fallback, self.app_key))
        while(old_msg):
            log.debug('handle message:%s'%old_msg)
            try:
                simplejson.loads(old_msg)
                self.send_message({'type': 'message','data': old_msg})
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
            self.send_message(message)


    def feedback(self):
        """
        从apns获取feedback,处理无效token
        """
        while(True):
            try:
                for (token,fail_time) in self.apns.feedback_server.items():
                    log.debug('push message fail to send to %s.'%token)
                    #TODO 清除不再有效的Token
            except:
                self.log_error()
                self.reconnect()
            time.sleep(10)


if __name__ == '__main__':
    if len(sys.argv) >= 2:
        notifier = Notifier(job=sys.argv[1])
    else:
        notifier = Notifier()
    notifier.run()

