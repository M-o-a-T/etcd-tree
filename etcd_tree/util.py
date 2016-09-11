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
import asyncio
from etcd import EtcdNotFile,EtcdNotDir,EtcdKeyNotFound

async def to_etcd(conn, path, data, delete=False):
	mod = None
	def modu(m):
		nonlocal mod
		if mod is None:
			mod = m
		elif m is None:
			return # pragma: no cover
		elif mod < m:
			mod = m
	if isinstance(data,dict):
		if delete:
			try:
				r = await conn.read(path)
			except EtcdKeyNotFound:
				pass
			else:
				for c in r.child_nodes:
					n = c.name
					if c.name not in data:
						modu((await conn.delete(c.key,dir=c.dir,recursive=True)).modifiedIndex)
		for k,v in data.items():
			modu((await to_etcd(conn, path+"/"+k, v, delete=delete)))
	else:
		try:
			cur = await conn.read(path)
		except EtcdNotDir as e:
			modu((await conn.delete(e.payload['cause'],dir=False,recursive=False)).modifiedIndex)
		except EtcdKeyNotFound:
			pass
		else:
			if data == cur.value:
				modu(cur.modifiedIndex)
				return mod
		try:
			modu((await conn.set(path,str(data))).modifiedIndex)
		except EtcdNotFile:
			await conn.delete(path,dir=True,recursive=True)
			modu((await conn.set(path,str(data))).modifiedIndex)
	return mod

async def from_etcd(conn, path, dump=False):
	res = await conn.read(path, recursive=True)

	data = {}
	if dump:
		data['_'] = dict((k,v) for k,v in res.__dict__.items() if v)
		data['_'].pop('_children',None)
		if res.value is not None:
			return data
	elif res.value is not None:
		return res.value
	def d_add(tree, res):
		for t in tree:
			n = t['key']
			n = n[n.rindex('/')+1:]
			if 'value' in t:
				if dump:
					res[n] = t
				else:
					res[n] = t['value']
			else:
				sd = {}
				if dump:
					sd['_'] = t.copy()
					sd['_'].pop('nodes',None)
				res[n] = sd
				d_add(t.get('nodes',()),sd)
	d_add(res._children,data)
	return data

# this reads our configuration from yaml

from yaml import safe_load
from yaml.constructor import SafeConstructor

def from_yaml(path):
	with open(path) as f:
		return yaml.safe_load(f)

# this is a decorator for an instance-or-class method

from functools import wraps

class hybridmethod(object):
	def __init__(self, func):
		self.func = func

	def __get__(self, obj, cls):
		context = obj if obj is not None else cls

		@wraps(self.func)
		def hybrid(*args, **kw):
			return self.func(context, *args, **kw)

		# optional, mimic methods some more
		hybrid.__func__ = hybrid.im_func = self.func
		hybrid.__self__ = hybrid.im_self = context

		return hybrid


from importlib import import_module
def import_string(name):
	"""Import a module, or resolve an attribute of a module."""
	name = str(name)
	try:
		return import_module(name)
	except ImportError:
		if '.' not in name:
			raise
		module, obj = name.rsplit('.', 1)
		try:
			return getattr(import_string(module),obj)
		except AttributeError:
			raise AttributeError(name) from None
