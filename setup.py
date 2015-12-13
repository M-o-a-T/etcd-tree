#!/usr/bin/python3
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division, unicode_literals
##
##  This file is part of etcTree, a dynamic and Pythonic view of
##  whatever information you tend to store in etcd.
##
##  etcTree is Copyright © 2015 by Matthias Urlichs <matthias@urlichs.de>,
##  it is licensed under the GPLv3. See the file `README.rst` for details,
##  including optimistic statements by the author.
##
##  This program is free software: you can redistribute it and/or modify
##  it under the terms of the GNU General Public License as published by
##  the Free Software Foundation, either version 3 of the License, or
##  (at your option) any later version.
##
##  This program is distributed in the hope that it will be useful,
##  but WITHOUT ANY WARRANTY; without even the implied warranty of
##  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##  GNU General Public License (included; see the file LICENSE)
##  for more details.
##
##  This header is auto-generated and may self-destruct at any time,
##  courtesy of "make update". The original is in ‘scripts/_boilerplate.py’.
##  Thus, do not remove the next line, or insert any blank lines above.
##
import logging
logger = logging.getLogger(__name__)
##BP

#
# setup.py for etcTree

from sys import version
import os

#from distutils.core import setup
from setuptools import setup

from setuptools.command.test import test as TestCommand

def get_version(fname='etcd_tree/__init__.py'):
    with open(fname) as f:
        for line in f:
            if line.startswith('__VERSION__'):
                return eval(line.split('=')[-1])

class PyTest(TestCommand):
    user_options = [('pytest-args=', 'a', "Arguments to pass to py.test")]

    def initialize_options(self):
        TestCommand.initialize_options(self)
        self.pytest_args = ['--assert=plain']

    def run_tests(self):
        #import here, cause outside the eggs aren't loaded
        import pytest
        errno = pytest.main(self.pytest_args)
        sys.exit(errno)


name='etcd_tree'

if version < '3.5':
    sys.exit('Error: Python 3.5 or newer is required. Current version:\n %s'
             % sys.version)

setup(
    name = name,
    version = '.'.join(str(x) for x in get_version()),
    description = 'Dynamic etcd state',
    long_description = '''\
etcTree is a dynamic, object-oriented view of an etcd (sub)tree
with bi-directional updates.
''',
    classifiers=[
        "Topic :: System :: Distributed Computing",
        "Topic :: Software Development :: Libraries",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Topic :: Database :: Front-Ends",
    ],
    keywords='etcd asyncio',
    author = 'Matthias Urlichs',
    author_email = 'matthias@urlichs.de',
    url = 'https://github.com/m-o-a-t/etcd-tree',
    download_url = 'https://github.com/M-o-a-T/etcd-tree/archive/master.zip',
    license = 'GPL',

    zip_safe = False, 
    packages = ('etcd_tree',),
    package_data = { '': ['*.glade']},
    scripts = (
        'viewer/etcd-tree',
        'scripts/etcd2yaml',
        'scripts/yaml2etcd',
        'scripts/etcdmon',
        ),
    install_requires = """\
gi >= 3.12
aio_etcd >= 0.4.3
""",
    setup_requires = """\
coverage
pytest
pytest-cov
""",
    test_suite='pytest.collector',
    cmdclass = {'test': PyTest},
    )
