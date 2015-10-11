# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division, unicode_literals
##
##  This file is part of MoaTree, the Master of all Things' etcd support.
##
##  MoaTree is Copyright © 2015 by Matthias Urlichs <matthias@urlichs.de>,
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

import etcd
from etcd.client import Client
from .node import mtBase,mtValue,mtDir
from threading import Thread,Lock,Condition
from multiprocessing import Process,Queue
#from queue import Queue
import weakref

class _NOTGIVEN: pass

class EtcClient(object):
	def __init__(self, root="", **args):
		assert (root == '' or root[0] == '/')
		self.root = root
		self.args = args
		self.client = Client(**args)
		self.watched = weakref.WeakValueDictionary()
		try:
			self.last_mod = self.client.read(root).etcd_index
		except etcd.EtcdKeyNotFound:
			self.last_mod = self.client.write(root, value=None, dir=True).etcd_index

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

	def read(self, key, **kw):
		return self.client.read(self._extkey(key), **kw)
	
	def delete(self, key, **kw):
		res = self.client.delete(self._extkey(key), **kw)
		self.last_mod = res.modifiedIndex
		return res
	
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
			kw['prevExists'] = True
		elif not kw.get('append',False):
			kw['prevExists'] = False
			if index is not None:
				kw['prevIndex'] = index
			if prev is not _NOTGIVEN:
				kw['prevValue'] = prev

		res = self.client.write(key, value=value, **kw)
		self.last_mod = res.modifiedIndex
		logger.debug("written: index is %d", res.etcd_index)
		return res

	def tree(self, key, cls, immediate=True, static=False):
		"""\
			Generate an object tree, populate it, and update it.

			If @immediate is set, run a recursive query and grab everything now.
			Otherwise fill the tree in the background.
			@static=True turns off the tree's auto-update.
			"""

		res = self.watched.get(key,None)
		if res:
			return res
			
		res = self.client.read(self._extkey(key), recursive=immediate)
		w = None if static else EtcWatcher(self,key,res.etcd_index)
		root = cls(conn=self, watcher=w, name=None, seq=res.modifiedIndex)

		if immediate:
			def d_add(tree, node):
				for t in tree:
					n = t['key']
					n = n[n.rindex('/')+1:]
					if t.get('dir',False):
						sd = node._ext_lookup(n, dir=True, seq=res.etcd_index)
						d_add(t['nodes'],sd)
					else:
						node._ext_lookup(n, dir=False, value=t['value'], seq=res.etcd_index)
				node._set_up()
			d_add(res._children,root)
		else:
			def d_get(node, res):
				for c in res.children:
					n = c.key
					n = n[n.rindex('/')+1:]
					if c.dir:
						sd = node._ext_lookup(n,dir=True, seq=res.etcd_index)
						d_get(sd,self.client.read(c.key))
					else:
						node._ext_lookup(n,dir=False, value=c.value, seq=res.etcd_index)
				node._set_up()
			d_get(root, res)

		if w is not None:
			w.run(root)
		return root
		
class EtcWatcher(object):
	"""\
		Runs a watcher on a (sub)tree.

		@conn: the EtcClient to monitor.
		@key: the path to monitor, relative to conn.
		@seq: etcd_index to start monitoring from.
		"""
	writer = None
	def __init__(self, conn,key,seq):
		self.conn = conn
		self.key = key
		self.extkey = self.conn._extkey(key)
		self.q = Queue()
		self.last_read = seq
		self.last_seen = seq
		self.reader = Process(target=_watch_read, args=(weakref.proxy(self),self.last_read,), kwargs=conn.args, name="Watch "+key)
		self.reader.start()
		self.uptodate = Condition()

	def __del__(self):
		self._kill(abnormal=False)

	def _kill(self, abnormal=True):
		"""Tear down everything"""
		r,self.reader = self.reader,None
		if r:
			r.terminate()
			try:
				r.join(timeout=10)
			except Exception as e:
				logger.exception(e)
		if self.q is not None:
			try:
				self.q.put(None)
			except BrokenPipeError:
				pass
			self.q = None
		w,self.writer = self.writer,None
		if w:
			try:
				w.join(timeout=10)
			except RuntimeError:
				# cleanup may happen from within this thread
				pass
			except Exception as e:
				logger.exception(e)

		
	def run(self, root):
		self.root = weakref.ref(root)
		self.writer = Thread(target=_watch_write, args=(weakref.proxy(self),), name="Update "+self.key)
		self.writer.start()
		
	def sync(self, mod=None):
		if mod is None:
			mod = self.conn.last_mod
		logger.debug("Syncing, wait for %d",mod)
		with self.uptodate:
			while self.writer and self.last_seen < mod:
				self.uptodate.wait(10)
		logger.debug("Syncing, done, at %d",self.last_seen)


def _watch_read(self,last_read,**kw):
	"""\
		Task which reads from etcd and queues the events received.

		This *needs* to be a separate process because the actual HTTP
		connection the reader ends up waiting for is not stored in any
		object, thus we can't close it, thus we can't terminate the
		thread, thus our program will hang forever.
		"""
	logger.info("READER started")
	conn = Client(**kw)
	key = self.extkey
	try:
		while True:
			for x in conn.eternal_watch(key, index=self.last_read+1, recursive=True):
				logger.debug("IN: %s",repr(x.__dict__))
				try:
					self.q.put(x)
				except BrokenPipeError:
					return
				self.last_read = x.modifiedIndex
	except BaseException as e:
		try:
			self.q.put(e)
		except BrokenPipeError:
			pass
		self.q = None
		logger.exception(e)
		raise
	finally:
		logger.info("READER ended")

def _watch_write(self):
	"""\
		Task which processes the event queue.

		This task is easier: it waits on the queue, which we can send a
		terminating token into from both sides. It also wants to update
		our objects, so ...
		"""
	logger.info("WRITER started")
	try:
		while True:
			# Drop references so that termination works
			root = r = None
			x = self.q.get()
			try:
				root = r = self.root()
			except ReferenceError:
				pass
			if x is None or r is None or isinstance(x,BaseException):
				if r is not None:
					r._freeze()
				self._kill()
				return

			try:
				logger.debug("RUN: %s",repr(x.__dict__))
				assert x.key.startswith(self.extkey), (x.key,self.key, x.modifiedIndex)
				key = x.key[len(self.extkey):]
				assert key[0] == '/'
				key = tuple(k for k in key.split('/') if k != '')
				if x.action in {'delete','expire'}:
					try:
						for k in key:
							r = r._ext_lookup(k)
						r._ext_delete()
					except (KeyError,AttributeError):
						pass
				elif x.dir:
					for k in key:
						r = r._ext_lookup(k, dir=True)
				else:
					for n,k in enumerate(key):
						r = r._ext_lookup(k, dir=n<len(key)-1)
					r._ext_update(x.value)

				with self.uptodate:
					self.last_seen = x.modifiedIndex
					self.uptodate.notify_all()
					logger.debug("DONE %d",x.modifiedIndex)

			except Exception as e:
				logger.exception(e)
				self._kill()
				raise
	finally:
		logger.info("WRITER ended")
