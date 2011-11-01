#encoding=utf-8

import sys,os,time,atexit
from signal import SIGTERM

class Daemon(object):
    """
    继承本类，实现一个run方法即可使之以守护线程的方式运行了。
    """
    def __init__(self,pidfile="/tmp/my-daemon.pid",stdin="/dev/null",stdout="/dev/null",stderr="/dev/null"):
	    self.stdin = stdin
	    self.stdout = stdout
	    self.stderr = stderr
	    self.pidfile = pidfile

    def daemonize(self):
	    """
	    连Fork两次来达到daemon的目的。
	    """
	    #fork 第一次
	    try:
	        pid = os.fork()
	        if pid > 0:
		        sys.exit(0)

	    except OSError,e:
	        sys.stderr.wirte('fork #1 faild: %d (%s)\n'%(e.errno,e.strerror))
	        sys.exit(1)

	    os.chdir('/')
	    os.setsid()
	    os.umask(0)

	    #fork 第2次
	    try:
	        pid = os.fork()
	        if pid > 0:
		        sys.exit(0)

	    except OSError,e:
	        sys.stderr.wirte('fork #2 faild: %d (%s)\n'%(e.errno,e.strerror))
	        sys.exit(1)

	    sys.stdout.flush()
	    sys.stderr.flush()

	    so = file(self.stdout,'a+')
	    se = file(self.stderr,'a+',0)
	    si = file(self.stdin,'r')

	    os.dup2(si.fileno(),sys.stdin.fileno())
	    os.dup2(so.fileno(),sys.stdout.fileno())
	    os.dup2(se.fileno(),sys.stderr.fileno())

	    atexit.register(self.delpid)

	    pid = str(os.getpid())
	    pf = file(self.pidfile,'w+')
	    pf.write("%s\n"%pid)
            pf.close()

            print 'the pidfile is %s'%self.pidfile

	    print 'now,the output redirect to log file'

    def delpid(self):
	    os.remove(self.pidfile)

    def getpid(self):
	    try:
	        pf = file(self.pidfile,'r')
	        pid = int(pf.read().strip())
	        pf.close()
	    except:
	        pid = None

	    return pid

    def start(self):
    	"""
	    启动守护进程
	    """
        print 'Starting ......'
        if self.getpid():
	        message = "pidfile %s already exist,Daemon aready running?\n"
	        sys.stderr.write(message % self.pidfile)
	        sys.exit(1)
        self.daemonize()
        self.run()

    def stop(self):
        """
        停止守护进程
        """
        print 'Stopping ......'
        pid = self.getpid()
        if not pid:
            message = "pidfile %s not exist,Daemon not running\n"
            sys.stderr.write(message % self.pidfile)
            return
        try:
            while 1:
                os.kill(pid,SIGTERM)
                time.sleep(0.1)
        except OSError,err:
            err = str(err)
            if err.find("No such process") > 0:
                if os.path.exists(self.pidfile):
                    os.remove(self.pidfile)
            else:
                print str(err)
            sys.exit(1)

    def restart(self):
	    """
	    重启守护进程
	    """
	    print 'Restarting .......'
	    self.stop()
	    self.start()

    def run(self):
	    pass
