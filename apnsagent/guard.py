#encoding=utf-8
import time
import os
import sys
from settings import *
import redis
import threading
from logger import log

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.append(os.getcwd())

from daemon import Daemon
from notification import Notifier

class PushGuard(Daemon):
    """推送服务的主程序，主要职责:
    - 从指定目录读取一批app的配置文件(证书和Key)，并为之创建相应的推送和
    Feedback线程。
    - 定时轮询目录，在运行时对推送线程进行增删改管理
    """

    def run(self):
        """读取一个目录，遍历下面的app文件夹，每个app启动一到两条线程对此提供服
        务,一条用来发推送，一条用来收feedback
        """
        apps = [app for app in os.listdir(APPS_DIR)
                if os.path.isdir(os.path.join(APPS_DIR, app))]

        for app in apps:
            # 文件夹下面会有production,develop两个子目录，分别放不同的Key及Cert
            # 文件
            if os.path.exists(os.path.join(APPS_DIR, app, DEVELOP_DIR)):
                self.make_worker_threads(app, develop=True)
            if os.path.exists(os.path.join(APPS_DIR, app, PRODUCTION_DIR)):
                self.make_worker_threads(app)

        #TODO 启动一条监控的线程,允许动态增加推送应用及移除推送应用。使用
        #inotify或队列来实现监听变动。inotify或许不错哦。


    def make_worker_threads(self, app, develop=False):
        app_key = app
        path = os.path.join(APPS_DIR, app, DEVELOP_DIR) \
               if develop else \
               os.path.join(APPS_DIR, app, PRODUCTION_DIR)
        cer_file = os.path.join(path, CER_FILE)
        key_file = os.path.join(path, KEY_FILE)

        if not (os.path.exists(cer_file) and os.path.exists(key_file)):
            return 
        
        kwargs = {
            'develop': develop,
            'app_key': app_key,
            'cer_file': cer_file,
            'key_file': key_file
        }
            
        push_job = threading.Thread(target=self.push, kwargs=kwargs)
        feedback_job = threading.Thread(target=self.feedback, kwargs=kwargs)

        push_job.start()
        feedback_job.start()

        push_job.join()
        feedback_job.join()

        
    def push(self, develop, app_key, cer_file, key_file):
        notifier = Notifier('push', develop, app_key, cer_file, key_file)
        notifier.run()


    def feedback(self, develop, app_key, cer_file, key_file):
        notifier = Notifier('feedback', develop, app_key, cer_file, key_file)
        notifier.run()


if __name__ == '__main__':
    stdout = os.path.join(PROJECT_ROOT,'std.out.log')
    stderr = os.path.join(PROJECT_ROOT,'std.err.log')
    path = os.getcwd().replace(os.sep,'_')
    daemon = PushGuard('/tmp/%s.pid'%path,stdout=stdout,stderr=stderr)
    if len(sys.argv) >= 2:
        command = sys.argv[1]
        if command == 'start':
            daemon.start()
        elif command == 'run':
            daemon.run()
        elif command == 'stop':
            daemon.stop()
        elif command == 'restart':
            daemon.restart()
        else:
            print 'unkonwn command'
            sys.exit(2)
        sys.exit(0)
    else:
        print 'Usage: %s start(daemon)|run|stop|restart|' % sys.argv[0]
        sys.exit(2)




