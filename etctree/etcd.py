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
This is the etcd interface.
"""

import aioetcd as etcd
from aioetcd.client import Client
import asyncio
import weakref
import inspect

from .node import mtRoot

class _NOTGIVEN: pass

class EtcClient(object):
	last_mod = None
	def __init__(self, root="", loop=None, **args):
		assert (root == '' or root[0] == '/')
		self.root = root
		self.args = args
		self._loop = loop if loop is not None else asyncio.get_event_loop()
		self.client = Client(loop=loop, **args)
		self.watched = weakref.WeakValueDictionary()
		self.types = {}
	
	@asyncio.coroutine
	def _init(self):
		if self.last_mod is not None:
			return
		try:
			self.last_mod = (yield from self.client.read(self.root)).etcd_index
		except etcd.EtcdKeyNotFound:
			self.last_mod = (yield from self.client.write(self.root, value=None, dir=True)).etcd_index

	def __del__(self):
		try:
			del self.client
		except AttributeError:
			# already gone
			pass

	def _extkey(self, key):
		key = str(key)
		assert (key == '' or key[0] == '/')
		return self.root+key

	def get(self, key, **kw):
		return self.client.get(self._extkey(key), **kw)
	get._is_coroutine = True

	def read(self, key, **kw):
		return self.client.read(self._extkey(key), **kw)
	read._is_coroutine = True
	
	@asyncio.coroutine
	def delete(self, key, **kw):
		res = yield from self.client.delete(self._extkey(key), **kw)
		self.last_mod = res.modifiedIndex
		return res
	
	@asyncio.coroutine
	def set(self, key, value, prev=_NOTGIVEN, index=None, **kw):
		"""\
			Either create or update a value.

			@key: the object path.

			@ttl: time-to-live in seconds.

			@append: generate a new guaranteed-unique and sequential entry.

			"""
		key = self._extkey(key)
		logger.debug("Write %s to %s with %s",value,key, repr(kw))
		if prev is _NOTGIVEN and index is None:
			kw['prevExist'] = False
		elif not kw.get('append',False):
			kw['prevExist'] = True
			if index is not None:
				kw['prevIndex'] = index
			if prev not in (None,_NOTGIVEN):
				kw['prevValue'] = prev

		res = yield from self.client.write(key, value=value, **kw)
		self.last_mod = res.modifiedIndex
		logger.debug("WROTE: %s",repr(res.__dict__))
		return res

	def register(self, name, sub=None):
		"""\
			Teach this node that a sub-node named @name is to be of type @sub.
			"""
		def defi(sub):
			self.types[name] = sub
			return sub
		if sub is None:
			return defi
		else:
			return defi(sub)

	@asyncio.coroutine
	def tree(self, key, cls=None, immediate=True, static=False, create=None):
		"""\
			Generate an object tree, populate it, and update it.
			if @create is True, create the directory node.

			If @immediate is set, run a recursive query and grab everything now.
			Otherwise fill the tree in the background.
			@static=True turns off the tree's auto-update.

			*Warning*: If you update the tree by direct assignment, you
			*must* call its `_wait()` coroutine in order to process them.
			The tree may or may not contain your updates before you do
			that.
			"""

		assert key[0] == '/'

		if not static:
			res = self.watched.get(key,None)
			if res is not None:
				return res
			
		if cls is None:
			cls = self.types.get(key,mtRoot)

		try:
			res = yield from self.client.read(self._extkey(key), recursive=immediate)
		except etcd.EtcdKeyNotFound:
			if create is False:
				raise
			res = yield from self.client.write(self._extkey(key), prevExist=False, dir=True, value=None)
		else:
			if create is True:
				raise etcd.EtcdAlreadyExist(self._extkey(key))
		w = None if static else EtcWatcher(self,key,res.etcd_index)
		root = cls(conn=self, watcher=w, name=None, seq=res.modifiedIndex,
			ttl=res.ttl if hasattr(res,'ttl') else None)

		if immediate:
			def d_add(tree, node):
				for t in tree:
					n = t['key']
					n = n[n.rindex('/')+1:]
					if t.get('dir',False):
						sd,is_new = node._ext_lookup(n, dir=True, seq=t['modifiedIndex'],
							ttl=res.ttl if hasattr(res,'ttl') else None)
						d_add(t.get('nodes',()),sd)
					else:
						node._ext_lookup(n, dir=False, value=t['value'], seq=t['modifiedIndex'],
							ttl=t['ttl'] if 'ttl' in t else None)
				node._updated()
				if w is not None:
					w.notify(node,"populate")
			d_add(res._children,root)
		else:
			@asyncio.coroutine
			def d_get(node, res):
				for c in res.children:
					if c is res:
						continue # pragma: no cover
					n = c.key
					n = n[n.rindex('/')+1:]
					if c.dir:
						sd,is_new = node._ext_lookup(n,dir=True, seq=res.modifiedIndex,
							ttl=res.ttl if hasattr(res,'ttl') else None)
						data = yield from self.client.read(c.key)
						yield from d_get(sd, data)
					else:
						node._ext_lookup(n,dir=False, value=c.value, seq=res.modifiedIndex,
							ttl=res.ttl if hasattr(res,'ttl') else None)
				node._updated()
				if w is not None:
					w.notify(node,"populate")
			yield from d_get(root, res)

		if w is not None:
			w._set_root(root)
			self.watched[key] = root
		return root
		
class EtcWatcher(object):
	"""\
		Runs a watcher on a (sub)tree.

		@conn: the EtcClient to monitor.
		@key: the path to monitor, relative to conn.
		@seq: etcd_index to start monitoring from.
		"""
	_reader = None
	def __init__(self, conn,key,seq):
		self.conn = conn
		self.key = key
		self.extkey = self.conn._extkey(key)
		self.last_read = seq
		self.last_seen = seq
		self._reader = asyncio.async(self._watch_read())
		self.uptodate = asyncio.Condition()
		self.notifier = EtcNotifier()

	def __del__(self): # pragma: no cover
		self._kill(abnormal=False)

	@asyncio.coroutine
	def notify(self, node, type):
		"""Send a change notification to all subscribers"""
		nodes = [(".",self.notifier)]
		if isinstance(node,tuple):
			kp = node
			node = None
		else:
			kp = node._keypath
		for p in kp:
			cn = set()
			for k,n in nodes:
				for nk,nn in n.items(p):
					cn.add((nk,nn))
				if k == "**":
					cn.add((k,n))
			if not cn:
				return
			nodes = cn
		for p,n in nodes:
			try:
				yield from n.notify(node,type)
			except Exception:
				logger.exception("Error in notifier %s", repr(n))

	def _kill(self, abnormal=True):
		"""Tear down everything"""
		#logger.warning("_KILL")
		r,self._reader = self._reader,None
		if r is not None:
			r.cancel()
			r = None
		if self.q is not None:
			yield from self.q.put(None)
			self.q = None
		
	def _set_root(self, root):
		self.root = weakref.ref(root)
		
	def monitor(self, *path):
		"""\
			Register a monitor function.

			@watcher.monitor("/foo/bar/baz")
			def on_change(node, type):
				pass

			@node is the affected tree node, or a tuple to its path if unavailable.
			@type is dir/set/update/delete/expire
			@path path can be a /- or .-separated string,
			or a list of path elements.
			"""
		if len(path) == 1:
			path = path[0]
			if path[0] == "/":
				path = tuple(p for p in path.split('/') if p != '')
			else:
				path = path.split(".")

		mon = self.notifier
		for p in path:
			mon = mon.step(p)
		return mon.register

	@asyncio.coroutine
	def sync(self, mod=None):
		"""Wait for pending updates"""
		if mod is None:
			mod = self.conn.last_mod
		logger.debug("Syncing, wait for %d",mod)
		try:
			yield from self.uptodate.acquire()
			while self._reader is not None and self.last_seen < mod:
				yield from self.uptodate.wait() # pragma: no cover
				                                # processing got done during .acquire()
		finally:
			self.uptodate.release()
		logger.debug("Syncing, done, at %d",self.last_seen)

	@asyncio.coroutine
	def _watch_read(self): # pragma: no cover
		"""\
			Task which reads from etcd and processes the events received.
			"""
		logger.info("READER started")
		conn = Client(**self.conn.args)
		key = self.extkey
		try:
			while True:
				@asyncio.coroutine
				def cb(x):
					logger.debug("IN: %s",repr(x.__dict__))
					try:
						yield from self._watch_write(x)
					except Exception:
						logger.exception("Error in write watcher")
						# XXX TODO trigger a major error
					self.last_read = x.modifiedIndex

				yield from conn.eternal_watch(key, index=self.last_read+1, recursive=True, callback=cb)

		except GeneratorExit:
			raise
		except BaseException as e:
			logger.exception("READER died")
			raise
		finally:
			logger.info("READER ended")

	@asyncio.coroutine
	def _watch_write(self, x):
		"""\
			Callback which processes incoming events
			"""
		# Drop references so that termination works
		r = self.root()
		if r is None:
			raise etcd.StopWatching

		logger.debug("RUN: %s",repr(x.__dict__))
		assert x.key.startswith(self.extkey), (x.key,self.key, x.modifiedIndex)
		key = x.key[len(self.extkey):]
		key = tuple(k for k in key.split('/') if k != '')
		if x.action in {'delete','expire'}:
			try:
				for n,k in enumerate(key):
					r,is_new = r._ext_lookup(k)
					if r is None: # pragma: no cover
						break
				else:
					yield from self.notify(r, x.action)
					r._ext_delete()
			except (KeyError,AttributeError): # pragma: no cover
				r = None
			if r is None:
				yield from self.notify(key, x.action)
		else:
			is_new = False
			for n,k in enumerate(key):
				if is_new:
					yield from self.notify(r, "dir")
				r,is_new = r._ext_lookup(k, dir=True if x.dir else n<len(key)-1)
				if r is None:
					break # pragma: no cover
			else:
				kw = {}
				if hasattr(x,'ttl'): # pragma: no branch
					kw['ttl'] = x.ttl
				r._ext_update(x.value, seq=x.modifiedIndex, **kw)
			yield from self.notify(r if r is not None else key, x.action)

		yield from self.uptodate.acquire()
		try:
			self.last_seen = x.modifiedIndex
			self.uptodate.notify_all()
			logger.debug("DONE %d",x.modifiedIndex)
		finally:
			self.uptodate.release()

class EtcNotifier(dict):
	def __init__(self):
		self.callbacks = set()
		self.nodes = {}
	
	def __getitem__(self,key):
		return self.nodes[key]
	
	def step(self,key):
		"""Lookup with auto-generation of new nodes"""
		res = self.nodes.get(key,None)
		if res is None:
			self.nodes[key] = res = EtcNotifier()
		return res
	
	def items(self,key):
		"""\
			Enumerate entries matching this key.
			Yields (name,sub-entry) tuples.
			Note that a name of "**" is supposed to match a whole subtree,
			so your matching algorithm needs to carry it over.
			"""
		res = self.nodes.get(key,None)
		if res is not None:
			yield key,res
		res = self.nodes.get('*',None)
		if res is not None:
			yield "*",res
		res = self.nodes.get('**',None)
		if res is not None:
			yield "**",res
		
	def register(self, proc):
		"""Register a callback on this node"""
		self.callbacks.add(proc)
		return proc
	
	def __hash__(self):
		return id(self)

	@asyncio.coroutine
	def notify(self, node,type):
		"""Run notification calls for this node"""
		for p in self.callbacks:
			try:
				res = p(node,type)
				if isinstance(res, asyncio.Future) or inspect.isgenerator(res):
					yield from res
			except Exception:
				logger.exception("Error in '%s' callback for %s: %s ",type,repr(node),repr(p))

