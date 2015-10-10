#!/usr/bin/python3
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division, unicode_literals
##
##  This file is part of MoaTree, the Master of all Things.
##
##  MoaTree is Copyright © 2007-2015 by Matthias Urlichs <matthias@urlichs.de>,
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
##BP

#
# setup.py for MoaTree

from sys import version
import os
from moatree import VERSION

#from distutils.core import setup
from setuptools import setup

name='moatree'

if version < '3.4':
    sys.exit('Error: Python-3.4 or newer is required. Current version:\n %s'
             % sys.version)

setup(
    name = name,
    version = VERSION,
    description = 'State tree for home automation',
    long_description = '''\
MoaTree is a coherent config and status database, originally intended for home automation.
Needless to say, it *can* be used for other things.

MoaTree features an object interface based on etcd and good intentions.

There's clear separation of physical devices, logical state, transient
information (errors and pings) which facilitates using many small programs
which do one thing well, rather than home automation behemoths which need
to know how to talk to everything. (You can still do that, though.)

''',
    author = 'Matthias Urlichs',
    author_email = 'matthias@urlichs.de',
    url = 'https://github.com/m-o-a-t/moatree',
	download_url = 'http://netz.smurf.noris.de/cgi/gitweb?p=moatree.git;a=snapshot;h=master',
    license = 'GPL',

	zip_safe = False, 
    packages = ('moatree',),
	package_data = { '': ['*.glade']},
    scripts = ('viewer/etcd-tree.py',),
	install_requires = """\
gi >= 3.12
""",
    )
