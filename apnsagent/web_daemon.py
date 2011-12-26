import redis
from flask import Flask
app = Flask(__name__)

from guard import *

rds = redis.Redis()

@app.route("/")
def hello():
    return "Hello World!"

@app.route("/apps")
def echo_apps():
    return str(rds.hkeys("counter"))

@app.route("/msg_count/<who>")
def echo_msg_count(who):
    return str(rds.hget("counter",who))

@app.route("/fail_msg_count/<who>")
def fail_echo_msg_count(who):
    if(who in msg_counter):
        return  who + ":" + str(fail_msg_counter[who])
    else:
        return "no such an app"

@app.route("/bad_tokens/<who>")
def echo_bad_tokens(who):
    return str(rds.smembers('%s:%s' % (constants.INVALID_TOKENS,who)))

@app.route("/x")
def echo():
    global server
    return str(len(server.notifiers))

def start_server():
     app.run()

web_daemon = "start web daemon"
server = None

def start_web_daemon(serv):
    global web_daemon
    global server
    server = serv
    print web_daemon
    web_daemon = threading.Thread(target=start_server)
    web_daemon.setDaemon(True)
    web_daemon.start()
