#encoding=utf-8

import logging
import os.path
import sys

"""
日志使用方法：
from logger import log

log.info('your info')
log.debug('heyhey')

"""

LOG_LEVEL = logging.DEBUG # 日志的输出级别，有 NOTSET, DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FORMAT = '[%(asctime)s] %(funcName)s(%(filename)s:%(lineno)s) [%(levelname)s]:%(message)s' # 日志的输出格式

log = logging.getLogger()
log.setLevel(LOG_LEVEL)

def create_log(log_file='apnsagent.log'):
    global log
    
    formatter = logging.Formatter(LOG_FORMAT)
    filehandler = logging.FileHandler(log_file)
    filehandler.setFormatter(formatter)
    log.addHandler(filehandler)

create_log = create_log

def log_ex(msg=None):
    if msg:
        log.error(msg)
    excinfo = sys.exc_info()
    log.error(excinfo[0])
    log.error(excinfo[1])
    return excinfo
