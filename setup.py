#!/usr/bin/env python

from setuptools import setup
from apnsagent import VERSION

url="https://github.com/jeffkit/apnsagent"

long_description="A simple apns agent server and client lib in python"

setup(name="apnsagent",
      version=VERSION,
      description="APNS agent Server & client",
      maintainer="jeff kit",
      maintainer_email="bbmyth@gmail.com",
      url = url,
      long_description=long_description,
      scripts = ['apnsagent/bin/apnsagent-server.py'],
      packages=['apnsagent']
     )
