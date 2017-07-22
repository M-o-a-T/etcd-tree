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

"""\
This is the core of etcTree, the object tree.
"""

import os
import asyncio

__VERSION__ = (0,24,1)

import warnings
warnings.filterwarnings('ignore', category=ResourceWarning)

async def client(cfg=None, loop=None):
	if cfg is None:
		cfg = os.environ.get("ETCD_CFG","/etc/etcd_tree.cfg")
	if not isinstance(cfg,dict): # pragma: no branch
		from .util import from_yaml
		cfg = from_yaml(cfg)

	from .etcd import EtcClient
	c = EtcClient(loop=loop, **cfg['config']['etcd'])
	await c.start()
	return c

from .etcd import *
from .node import *

