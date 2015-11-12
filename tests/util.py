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

import os
from yaml import safe_load
from yaml.constructor import SafeConstructor
import warnings
warnings.filterwarnings("ignore",category=PendingDeprecationWarning)
import pytest
import etcd

__ALL__ = ('cfg','cfgpath')

cfgpath = None

@pytest.fixture
def client(event_loop):
    """An interface to a clean etcd subtree"""
    kw = cfg['config']['etcd'].copy()
    r = kw.pop('root')

    from etctree.etcd import EtcClient
    c = EtcClient(root=r, **kw)
    event_loop.run_until_complete(c._init())
    try:
        event_loop.run_until_complete(c.client.delete(c.root, recursive=True))
    except etcd.EtcdKeyNotFound:
        pass
    event_loop.run_until_complete(c.client.write(c.root, dir=True, value=None))
    def dumper(client):
        from etctree.util import from_etcd
        return from_etcd(client.client,client.root)
    def feeder(client,data, delete=False,subtree=""):
        from etctree.util import to_etcd
        return to_etcd(client.client,client.root+subtree,data, delete=delete)
    type(c)._d = dumper
    type(c)._f = feeder

    return c
    
# load a config file
def load_cfg(cfg):
    global cfgpath
    if os.path.exists(cfg):
        pass
    elif os.path.exists(os.path.join("tests",cfg)):
        cfg = os.path.join("tests",cfg)
    elif os.path.exists(os.path.join(os.pardir,cfg)):
        cfg = os.path.join(os.pardir,cfg)
    else:
        raise RuntimeError("Config file '%s' not found" % (cfg,))

    cfgpath = cfg
    with open(cfg) as f:
        cfg = safe_load(f)

    kw = cfg['config']['etcd'].copy()
    r = kw.pop('root')

    from etcd.client import Client
    c = Client(**kw)
    try:
        c.delete(r, recursive=True)
    except etcd.EtcdKeyNotFound:
        pass
    return cfg

if __name__ == "__main__":
    # quick&dirty test
    cfg = load_cfg("test.cfg.sample")
    d = dict
    d = d(config=d(etcd=d(host='localhost',port=2379,root='/test/etctree')))
    assert cfg == d, (cfg,d)
else:
    cfg = load_cfg(os.environ.get('ETCTREE_TEST_CFG',"test.cfg"))

