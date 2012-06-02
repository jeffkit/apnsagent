#encoding=utf-8

from os import listdir
from os.path import isdir
from os.path import exists
from os.path import join

from constants import DEVELOP_DIR
from constants import PRODUCTION_DIR
from constants import CER_FILE
from constants import KEY_FILE
from constants import CONF_FILE
from apnsagent.logger import log
from ConfigParser import ConfigParser


def get_app_info(app_dir, app):
    app_info = {'app_key': app}

    dev_dir = join(app_dir, app, DEVELOP_DIR)
    if isdir(dev_dir) and exists(join(dev_dir, CER_FILE)) \
           and exists(join(dev_dir, KEY_FILE)):
        # 读配置文件
        conf = join(dev_dir, CONF_FILE)
        conf_dict = {}
        if exists(conf):
            config = ConfigParser()
            config.read(conf)
            conf_dict = dict(config.items('apnsagent'))
        app_info['develop'] = {'cer_file': join(dev_dir, CER_FILE),
                               'key_file': join(dev_dir, KEY_FILE),
                               'config': conf_dict}

    pro_dir = join(app_dir, app, PRODUCTION_DIR)
    if isdir(pro_dir) and exists(join(pro_dir, CER_FILE)) \
           and exists(join(pro_dir, KEY_FILE)):
        conf = join(pro_dir, CONF_FILE)
        log.debug('config file: %s' % conf)
        conf_dict = {}
        if exists(conf):
            log.debug('load config file')
            config = ConfigParser()
            config.read(conf)
            conf_dict = dict(config.items('apnsagent'))
            log.debug('config content %s' % conf_dict)
        app_info['production'] = {'cer_file': join(pro_dir, CER_FILE),
                                'key_file': join(pro_dir, KEY_FILE),
                                'config': conf_dict}
    return app_info


def get_apps(app_dir):
    return [d for d in listdir(app_dir) if isdir(join(app_dir, d))]
