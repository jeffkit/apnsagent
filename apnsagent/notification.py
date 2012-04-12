#encoding=utf-8
import sys
import re
import traceback

import simplejson
from apns import APNs, Payload
from apns import PayloadTooLargeError
from ssl import SSLError
import socket
import select
import redis
import time
import uuid
from datetime import datetime

from apnsagent import constants
from apnsagent.logger import log
from client import PushClient


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
        self.retry_time_max = 99  # 如果redis连接断开，重试99次
        self.retry_time = 0

        self.last_sent_time = datetime.now()

        self.apns = APNs(use_sandbox=self.develop,
                         cert_file=self.cert_file, key_file=self.key_file)

        self.server_info = server_info or {
            'host': '127.0.0.1',
            'post': 6379,
            'db': 0,
            'password': ''
            }

        self.client = PushClient(self.app_key, self.server_info)

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

    def log_error(self, message='message push fail'):
        self.rds.hincrby("fail_counter", self.app_key)
        log.error(message)
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

        self.push_fallback(fallback)
        self.consume_message(channel)

    def push_fallback(self, fallback):
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

    def consume_message(self, channel):
        # 再订阅消息队列
        try:
            pubsub = self.rds.pubsub()
            pubsub.subscribe('%s:%s' % (channel, self.app_key))
            log.debug('subscribe push job channel successfully')
            redis_channel = pubsub.listen()

            for message in redis_channel:
                self.retry_time = 0
                if 'kill' == message['data']:
                    break
                else:
                    self.send_message(message)
        except:
            # 连接redis不上, 睡眠几秒钟重试连接
            if self.retry_time <= self.retry_time_max:
                time.sleep(10)
                self.retry_time = self.retry_time + 1
                log.debug(u'redis cannot connect, retry %d' % self.retry_time)
                self.consume_message(channel)
            else:
                # 这时，需要Email通知管理员了
                log.error(u'retry time up, redis gone! help!')

        log.debug('i am leaving push')

    def feedback(self):
        """
        从apns获取feedback,处理无效token
        """
        while(self.alive):
            try:
                self.reconnect()
                for (token, fail_time) in self.apns.feedback_server.items():
                    log.debug('push message fail to send to %s.' % token)
                    # self.client.push(token, enhance=True)
                    # time.sleep(0.01)
                    self.rds.sadd('%s:%s' % (constants.INVALID_TOKENS,
                                             self.app_key),
                                  token)
            except:
                self.log_error('get feedback fail')
            time.sleep(60)

        log.debug('i am leaving feedback')


class EnhanceNotifier(Notifier):

    def run(self):
        self.rds = redis.Redis(**self.server_info)
        self.enhance_push()

    def handle_error(self, identifier, errorcode):
        """处理推送错误
        """
        log.debug('apns sent back an error: %s %d', identifier, errorcode)
        if errorcode == 8:
            # add token to invalid token set
            sent = self.rds.smembers('ENHANCE_SENT:%s' % self.app_key)
            for s in sent:
                data = simplejson.loads(s)
                if data['id'] != identifier:
                    continue
                token = data['token']
                self.rds.sadd('%s:%s' % (constants.INVALID_TOKENS,
                                         self.app_key),
                              token)
        else:
            log.debug('not invalid token, ignore error')

    def send_enhance_message(self, buff):
        identifier = uuid.uuid4().hex[:4]
        #expiry = int(time.time() + 5)
        expiry = 0

        try:
            data = simplejson.loads(buff)
            token = data['token']
            badge = data.get('badge', None)
            sound = data.get('sound', None)
            alert = data.get('alert', None)
            custom = data.get('custom', {})
            payload = SafePayload(sound=sound, badge=badge, alert=alert,
                                  custom=custom)
        except:
            return

        # 把发送的内容记录下来,记到redis，还得有一个定时器去清除过期的记录。
        data = simplejson.dumps({'id': identifier,
                                 'token': token,
                                 'expiry': expiry})
        self.rds.sadd('ENHANCE_SENT:%s' % self.app_key, data)
        self.apns.gateway_server.send_enhance_notification(token, payload,
                                                           identifier, expiry)

    def _reconnect_apns(self, clean=False):
        if clean:
            self.apns.gateway_server._disconnect()
            self.apns._gateway_connection = None
            if self.cli_sock in self.rlist:
                self.rlist.remove(self.cli_sock)
        self.apns.gateway_server._connect()
        self.cli_sock = self.apns.gateway_server._ssl
        self.rlist.append(self.cli_sock)

    def enhance_push(self):
        """
        使用增强版协议推送消息
        """
        self.host = 'localhost'
        index = self.rds.incr('ENHANCE_THREAD', 1)
        self.port = 9527 + index - 1
        self.rds.hset('ENHANCE_PORT',
                      ':'.join((self.app_key,
                                'dev' if self.develop else 'pro')),
                      self.port)

        srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv_sock.bind((self.host, self.port))
        srv_sock.listen(5)
        srv_sock.setblocking(0)

        self.apns.gateway_server._connect()
        self.cli_sock = self.apns.gateway_server._ssl

        log.debug('the apns client socket is : %s' % self.cli_sock)

        self.rlist = [srv_sock, self.cli_sock]
        self.wlist = []
        self.xlist = []

        while self.alive:
            rl, wl, xl = select.select(self.rlist,
                                       self.wlist,
                                       self.xlist, 10)

            if xl:
                for x in xl:
                    log.error('error occur %s' % x)

            if rl:
                log.debug('data to read %s' % rl)
                log.debug('rlist: %s' % self.rlist)
                for r in rl:
                    if r == srv_sock:
                        log.debug('connection from client!')
                        try:
                            new_sock, addr = srv_sock.accept()
                            self.rlist.append(new_sock)
                            continue
                        except socket.error:
                            pass
                    elif r == self.cli_sock:
                        log.debug('message from apns, some error eccour!')
                        error = self.apns.gateway_server.get_error()
                        if not error:
                            log.debug('apns drop the connection, reconnect!')
                            self._reconnect_apns(True)
                            continue
                        else:
                            self.handle_error(error[0], error[1])
                    else:
                        sk = self.apns.gateway_server._ssl
                        log.debug('message from client,will sent to %s' % sk)
                        buf = ''
                        try:
                            buf = r.recv(4096)
                        except socket.error:
                            self.rlist.remove(r)
                            r.close()
                            continue

                        if not buf:
                            # client close the socket.
                            self.rlist.remove(r)
                            r.close()
                            continue

                        try:
                            # 如果还没有连接，或闲置时间过长
                            now = datetime.now()
                            if not self.apns._gateway_connection:
                                log.debug('无连接,重连')
                                self._reconnect_apns(False)
                            elif (now - self.last_sent_time).seconds > 300:
                                log.debug('闲置时间过长，重连')
                                self._reconnect_apns(True)
                            log.debug('推送消息%s' % buf)
                            self.send_enhance_message(buf)
                            self.last_sent_time = now
                        except socket.error:
                            self.log_error('send notification fail, reconnect')
                            self._reconnect_apns(True)
                        except:
                            self.log_error('send notification fail with error')
