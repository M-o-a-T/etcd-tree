# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division, unicode_literals
##
##  This file is part of MoaT, the Master of all Things.
##
##  MoaT is Copyright © 2007-2015 by Matthias Urlichs <matthias@urlichs.de>,
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

# This feeds a simple recursive data structure to etcd.

from etcd import EtcdNotFile,EtcdNotDir,EtcdKeyNotFound
from dabroker.util import attrdict

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
	data = attrdict()
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
