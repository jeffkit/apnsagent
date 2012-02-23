#encoding=utf-8

import time
import os
import sys

from os import listdir
from os.path import isdir,isfile,exists,join

from constants import *


def get_app_info(app_dir,app):
  app_info = {'app_key':app}
  
  dev_dir = join(app_dir,app,DEVELOP_DIR)
  if isdir(dev_dir) and exists(join(dev_dir,CER_FILE)) and exists(join(dev_dir,KEY_FILE)):
    app_info['develop'] = {'cer_file':join(dev_dir,CER_FILE),'key_file':join(dev_dir,KEY_FILE)}
    
  pro_dir = join(app_dir,app,PRODUCTION_DIR)
  if isdir(dev_dir) and exists(join(pro_dir,CER_FILE)) and exists(join(pro_dir,KEY_FILE)):
    app_info['production'] = {'cer_file':join(pro_dir,CER_FILE),'key_file':join(pro_dir,KEY_FILE)}

  return app_info

def get_apps(app_dir):
  return [d for d in listdir(app_dir) if isdir(join(app_dir,d)) ]

