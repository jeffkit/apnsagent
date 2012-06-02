#!/usr/bin/env python
#encoding=utf-8

import time
import os
import sys

if os.getcwd() not in sys.path:
    sys.path.append(os.getcwd())

import threading
from optparse import OptionParser
from ConfigParser import ConfigParser

from notification import EnhanceNotifier
from notification import Notifier
from logger import log, create_log
from webserver import start_webserver

import simplejson
import utils
import redis


class PushGuard(object):
    """推送服务的主程序，主要职责:
    - 从指定目录读取一批app的配置文件(证书和Key)，并为之创建相应的推送和
    Feedback线程。
    - 定时轮询目录，在运行时对推送线程进行增删改管理
    """

    def __init__(self, app_dir, server_info):
        """初始化推送主进程，需要提供APP_DIR和SERVER_INFO参数
        app_dir: 存放应用信息的目录
        server_info: 用于连接redis的信息
        """
        assert app_dir, '"app_dir" argument is reqiured!'
        self.app_dir = app_dir
        self.server_info = server_info

        self.rds = redis.Redis(**self.server_info)

        #self.threads = {}
        self.notifiers = {}

    def run(self):
        """读取一个目录，遍历下面的app文件夹，每个app启动一到两条线程对此提供服
        务,一条用来发推送，一条用来收feedback
        """
        self.rds.set('ENHANCE_THREAD', 0)
        apps = utils.get_apps(self.app_dir)
        self.app_info = {}

        # 文件夹下面会有production,develop两个子目录，分别放不同的Key及Cert

        for app in apps:
            if app.startswith('.'):
                continue
            log.debug('getting ready for app : %s' % app)
            app_info = utils.get_app_info(self.app_dir, app)
            self.app_info[app] = app_info

            self.start_worker(app)

        start_webserver(self)
        self.watch_app()
        log.debug('just wait here,there are %d threads ' % len(self.notifiers))

        while True:
            time.sleep(10)

    def start_worker(self, app):
        log.debug('start an app : %s' % app)
        app_info = self.app_info[app]

        if 'production' in app_info:
            self.start_worker_thread(app, False,
                                     app_info['production']['cer_file'],
                                     app_info['production']['key_file'],
                                     app_info['production']['config'])
        if 'develop' in app_info:
            self.start_worker_thread(app, True,
                                     app_info['develop']['cer_file'],
                                     app_info['develop']['key_file'],
                                     app_info['develop']['config'])

    def start_worker_thread(self, app, dev, cer_file, key_file, conf):
        kwargs = {
            'develop': dev,
            'app_key': app,
            'cer_file': cer_file,
            'key_file': key_file,
            'server_info': self.server_info
        }
        # 检查配置里关于推送线程数的配置，启动相应数量的推送线程
        thread_cnt = 1
        log.debug('startting worker with config : %s' % conf)
        if conf:
            conf_prefix = 'config_dev:' if dev else 'config:'
            self.rds.hmset(conf_prefix + app, conf)
            try:
                thread_cnt = int(conf.get('worker', '1'))
            except:
                log.warn('invalid config of workers, just start one.')
        workers = []
        for cnt in range(thread_cnt):
            if cnt == 0:
                params = kwargs
                worker = threading.Thread(target=self.push, kwargs=params)
            else:
                params = kwargs.copy()
                params.update({'channel': cnt})
            worker = threading.Thread(target=self.push, kwargs=params)
            workers.append(worker)

        feedback_job = threading.Thread(target=self.feedback, kwargs=kwargs)
        enhance_job = threading.Thread(target=self.enhance, kwargs=kwargs)

        feedback_job.setDaemon(True)
        enhance_job.setDaemon(True)
        for w in workers:
            w.setDaemon(True)
            w.start()

        feedback_job.start()
        enhance_job.start()

    def stop_worker_thread(self, app_key):

        if (app_key + ":dev:push") in self.notifiers:
            self.notifiers[app_key + ":dev:push"].alive = False
            self.rds.publish('push_job_dev:%s' % app_key, 'kill')
            del self.notifiers[app_key + ":dev:push"]

        if (app_key + ":dev:feedback") in self.notifiers:
            self.notifiers[app_key + ":dev:feedback"].alive = False
            del self.notifiers[app_key + ":dev:feedback"]

        if (app_key + ":dev:enhance") in self.notifiers:
            self.notifiers[app_key + ":dev:enhance"].alive = False
            del self.notifiers[app_key + ":dev:enhance"]

        # 要看看有多少条推送线程，一条条退出
        if (app_key + ":pro:push") in self.notifiers:
            self.notifiers[app_key + ":pro:push"].alive = False
            self.rds.publish('push_job:%s' % app_key, 'kill')
            del self.notifiers[app_key + ":pro:push"]

        if (app_key + ":pro:feedback") in self.notifiers:
            self.notifiers[app_key + ":pro:feedback"].alive = False
            del self.notifiers[app_key + ":pro:feedback"]

        if (app_key + ":pro:enhance") in self.notifiers:
            self.notifiers[app_key + ":pro:enhance"].alive = False
            del self.notifiers[app_key + ":pro:enhance"]

    def watch_app(self):
        self.watcher = threading.Thread(target=self.app_watcher)
        self.watcher.setDaemon(True)
        self.watcher.start()

    def app_watcher(self):
        try:
            ps = self.rds.pubsub()
            ps.subscribe("app_watcher")
            channel = ps.listen()
            for message in channel:
                msg = simplejson.loads(message["data"])
                if(msg["op"] == "stop"):
                    self.stop_worker_thread(msg["app_key"])
                elif(msg["op"] == "start"):
                    self.start_worker(msg["app_key"])
        except:
            log.error('app_watcher fail,retry.')
            time.sleep(10)
            self.app_watcher()

    def push(self, develop, app_key, cer_file, key_file, server_info,
             channel=None):
        notifier = Notifier('push', develop, app_key,
                            cer_file, key_file, server_info, channel)

        channel = ':%s' % channel if channel else ''
        if develop:
            self.notifiers[app_key + ":dev:push" + channel] = notifier
        else:
            self.notifiers[app_key + ":pro:push" + channel] = notifier
        notifier.run()

    def feedback(self, develop, app_key, cer_file, key_file, server_info):
        notifier = Notifier('feedback', develop, app_key,
                            cer_file, key_file, server_info)
        if develop:
            self.notifiers[app_key + ":dev:feedback"] = notifier
        else:
            self.notifiers[app_key + ":pro:feedback"] = notifier
        notifier.run()

    def enhance(self, develop, app_key, cer_file, key_file, server_info):
        notifier = EnhanceNotifier('enhance', develop, app_key,
                                   cer_file, key_file, server_info)
        if develop:
            self.notifiers[app_key + ":dev:enhance"] = notifier
        else:
            self.notifiers[app_key + ":pro:enhance"] = notifier
        notifier.run()


def execute():
    parser = OptionParser(usage="%prog config [options]")
    parser.add_option("-f", "--folder", dest="app_dir",
                      help="folder where the certs and keys to stay")
    parser.add_option("-s", "--host", dest="host", default="127.0.0.1",
                      help="Redis host name or address")
    parser.add_option("-p", "--port", dest="port", default=6379, type="int",
                      help="Redis port")
    parser.add_option("-d", "--db", dest="db", default=0, type="int",
                      help="Redis database")
    parser.add_option("-a", "--password", dest="password", default="",
                      help="Redis password")
    parser.add_option("-l", "--log", dest="log",
                      help="log file")
    (options, args) = parser.parse_args(sys.argv)
    if options.log:
        create_log(options.log)
    else:
        create_log()

    if len(args) > 1:
        config = ConfigParser()
        config.read(args[1])
        guard = PushGuard(app_dir=config.get('app', 'app_dir'),
                          server_info={'host': config.get('redis', 'host'),
                                       'port': int(config.get('redis',
                                                              'port')),
                                       'db': int(config.get('redis', 'db')),
                                       'password': config.get('redis',
                                                              'password')})
    else:
        guard = PushGuard(app_dir=options.app_dir,
                          server_info={'host': options.host,
                                       'port': options.port,
                                       'db': options.db,
                                       'password': options.password})
    guard.run()

if __name__ == '__main__':
    execute()
