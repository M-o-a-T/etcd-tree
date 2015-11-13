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
from etctree import VERSION

#from distutils.core import setup
from setuptools import setup

name='etctree'

if version < '3.4':
    sys.exit('Error: Python-3.4 or newer is required. Current version:\n %s'
             % sys.version)

setup(
    name = name,
    version = VERSION,
    description = 'Dynamic etcd state',
    long_description = '''\
etcTree is a dynamic, object-oriented view of an etcd (sub)tree
with bi-directional updates.
''',
    author = 'Matthias Urlichs',
    author_email = 'matthias@urlichs.de',
    url = 'https://github.com/m-o-a-t/etctree',
    download_url = 'http://netz.smurf.noris.de/cgi/gitweb?p=etctree.git;a=snapshot;h=master',
    license = 'GPL',

    zip_safe = False, 
    packages = ('etctree',),
    package_data = { '': ['*.glade']},
    scripts = (
        'viewer/etcd-tree',
        'scripts/etcd2yaml',
        'scripts/yaml2etcd',
        'scripts/etcdmon',
        ),
    install_requires = """\
gi >= 3.12
aioetcd >= 0.4.2
""",
    setup_requires = """\
coverage
pytest
pytest-cov
""",
    )
