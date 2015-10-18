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

# This feeds a simple recursive data structure to etcd.

import os
import yaml
from etcd import EtcdNotFile,EtcdNotDir,EtcdKeyNotFound

def to_etcd(conn, path, data, delete=False):
	mod = None
	if isinstance(data,dict):
		if delete:
			r = conn.read(path)
			for c in r.children:
				n = c.key
				n = n[n.rindex('/')+1:]
				if n not in data:
					mod = conn.delete(c.key,dir=c.dir,recursive=True).modifiedIndex
		for k,v in data.items():
			mod = to_etcd(conn, path+"/"+k, v, delete=delete)
	else:
		try:
			cur = conn.read(path)
		except EtcdNotDir as e:
			mod = conn.delete(e.payload['cause'],dir=False,recursive=False).modifiedIndex
		except EtcdKeyNotFound:
			pass
		else:
			if data == cur.value:
				return mod
		try:
			mod = conn.set(path,str(data)).modifiedIndex
		except EtcdNotFile:
			conn.delete(path,dir=True,recursive=True)
			mod = conn.set(path,str(data)).modifiedIndex
	return mod

def from_etcd(conn, path):
	res = conn.read(path, recursive=True)
	data = {}
	def d_add(tree, res):
		for t in tree:
			n = t['key']
			n = n[n.rindex('/')+1:]
			if 'value' in t:
				res[n] = t['value']
			else:
				res[n] = sd = {}
				d_add(t.get('nodes',()),sd)
	d_add(res._children,data)
	return data

# this reads our configuration from yaml

from yaml import safe_load
from yaml.constructor import SafeConstructor

def from_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)

if __name__ == "__main__": # pragma: no cover
    # quick&dirty test
    cfg = from_yaml("test.cfg.sample")
    d = dict
    d = d(config=d(etcd=d(host='localhost',port=2379,root='/test/etctree')))
    assert cfg == d, (cfg,d)
else:
	## only use for testing
    cfg = from_yaml(os.environ.get('ETCTREE_TEST_CFG',"test.cfg"))

