import threading
import time

from apnsagent import constants
from apnsagent.constants import *

from redis import *
from flask import Flask, request, session, redirect, url_for, \
     render_template
from apnsagent.guard import *

app = Flask('apnsagent.webserver')
server = None
rds = Redis()
elapsed = time.time()

app.secret_key = 'A0Zr98j/3yX R~XHH!jmN]LWX/,?RT'


@app.route("/")
def hello():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    """
    if request.method == 'POST' \
       and request.form['username'] == USERNAME \
       and request.form['password'] == PASSWORD:
        session['username'] = USERNAME
        session['password'] = PASSWORD
        return redirect(url_for('mainlist'))
    else:
        return render_template('login.html')


@app.route("/list")
def mainlist():
    if session['username'] != USERNAME or session['password'] != PASSWORD:
        return redirect(url_for('login'))

    global server
    global rds

    seq = []
    cnt = 0
    for app in server.app_info:
        cnt += 1
        seq.append({'id': cnt,
                    'appname': app,
                    'total_count': rds.hget("counter", app) or 0,
                    'fail_count': rds.hget("fail_counter", app) or 0,
                    'develop': ('develop' in server.app_info[app]),
                    'production': ('production' in server.app_info[app]), })

    return render_template('notification_service.html',
                           seq=seq,
                           threads=len(server.app_info),
                           elapsed=('%.1d' % ((time.time() - elapsed) / 60)))


@app.route("/detail/<who>")
def detail(who):

    if session['username'] != USERNAME or session['password'] != PASSWORD:
        return redirect(url_for('login'))

    seq = []
    cnt = 0
    global rds
    tks = rds.smembers('%s:%s' % (constants.INVALID_TOKENS, who))
    for tk in tks:
        cnt += 1
        seq.append({'id': cnt, 'token': tk})

    return render_template('invalid_tokens.html', seq=seq,
                           appname=who, tokens_count=len(tks))


@app.route("/switch_on/<who>")
def switch_on(who):
    global server
    server.start_worker(who)
    return 'done'


@app.route("/switch_off/<who>")
def switch_off(who):
    global server
    server.stop_worker_thread(who)
    return 'done'


def start_server():
    app.run(port=5555, host='0.0.0.0')


def start_webserver(serv):
    print 'srarting webserver at the port 5555'
    global server
    server = serv
    web_daemon = threading.Thread(target=start_server)
    web_daemon.setDaemon(True)
    web_daemon.start()


if __name__ == '__main__':
    start_server()
