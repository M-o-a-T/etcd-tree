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

updlogger = logging.getLogger(__name__+'.update')
runlogger = logging.getLogger(__name__+'.run')
debug_id = 0

"""\
This declares nodes for the basic etcTree structure.
"""

import weakref
import time
import asyncio
from itertools import chain
from collections.abc import MutableMapping
from contextlib import suppress
import aio_etcd as etcd
from etcd import EtcdResult, EtcdKeyNotFound
from functools import wraps
from .util import hybridmethod
from traceback import print_exc

__all__ = ('EtcBase','EtcAwaiter','EtcDir','EtcRoot','EtcValue','EtcXValue',
	'EtcString','EtcFloat','EtcInteger','EtcBoolean',
	'ReloadData','ReloadRecursive',
	)

class _NOTGIVEN:
	pass
_later_idx = 1
_later_tag = 1

def EtcNull(*a,**k):
	raise RuntimeError("You can't assemble an etcd-tree node from scratch")

class ReloadData(ReferenceError):
	"""\
		The data type of a subtree cannot be decided without having the
		some data (first-level values) available.
		"""
	pass

class ReloadRecursive(ReferenceError):
	"""\
		The data type of a subtree cannot be decided without having the
		full data available.
		"""
	pass

class Env(object):
	def __getattr__(self,k):
		return None
	def __setattr__(self,k,v):
		try:
			object.__getattr__(self,k)
		except AttributeError:
			object.__setattr__(self,k,v)
		else:
			raise RuntimeError("Dup env assignment %s %s %s" % (self,k,v))
	def __delattr__(self,k):
		raise RuntimeError("You cannot do that. %s %s" % (self,k))

# etcd does not have a method to only enumerate direct children,
# so monkeypatch that in until it does

def child_nodes(self):
	for n in self._children:
		yield EtcdResult(None, n)
EtcdResult.child_nodes = property(child_nodes)
del child_nodes

# etcd does not have a method to get the node name without the whole
# keypath, so monkeypatch that in until it does

def name(self):
	if hasattr(self,'_name'):
		return self._name
	n = self.key
	self._name = n = n[n.rindex('/')+1:]
	return n
EtcdResult.name = property(name)
del name

# etcd does not have a method to look up a child node within a result,
# so monkeypatch that in until it does
# This is inefficient but is probably used rarely enough that it doesn't matter

def __getitem__(self, key):
	key = self.key+'/'+key
	for c in self._children:
		if c['key'] == key:
			return EtcdResult(None, c)
	raise KeyError(key)
EtcdResult.__getitem__ = __getitem__
del __getitem__

# Cancellable callback token

class MonitorCallback(object):
	def __init__(self, base,i,callback):
		self.base = weakref.ref(base)
		self.i = i
		self.callback = callback
	def cancel(self):
		base = self.base()
		if base is None:
			return # pragma: no cover
		base.remove_monitor(self.i)
	def __call__(self,x):
		return self.callback(x)

# Helper for possibly-asynchronously iterating through a tree

class _tagged_iter:
	def __init__(self,tree,tag, depth=0):
		assert type(tag) is bool or tag[0] == ':'
		self.trees = [(tree,0)]
		self.tag = tag
		self.depth = depth
		self.dirs = []
	async def __aiter__(self):
		return self
	def __iter__(self):
		return self
	async def __anext__(self):
		while not self.dirs:
			if not self.trees:
				raise StopAsyncIteration
			t,d = self.trees.pop()
			t = await t
			d += 1
			for k,v in t.items():
				if self.tag == (k[0] == ':') if type(self.tag) is bool else (k == self.tag):
					if not self.depth or self.depth == d:
						self.dirs.append(v)
				elif k[0] == ':':
					continue
				elif self.depth and self.depth <= d:
					continue
				elif isinstance(v,_EtcDir): # dir or awaiter
					self.trees.append((v,d))
		return (await self.dirs.pop())

	def __next__(self):
		while not self.dirs:
			if not self.trees:
				raise StopIteration
			t,d = self.trees.pop()
			d += 1
			for k,v in t.items():
				if self.tag == (k[0] == ':') if type(self.tag) is bool else (k == self.tag):
					if not self.depth or self.depth == d:
						self.dirs.append(v)
				elif k[0] == ':':
					continue
				elif self.depth and self.depth <= d:
					continue
				elif type(v) is EtcAwaiter:
					raise RuntimeError("'%s' is not preloaded. Use 'async for'." % ('/'.join(v.path),))
				elif isinstance(v,EtcDir):
					self.trees.append((v,d))
		return self.dirs.pop()

##############################################################################

class EtcBase(object):
	"""\
		Abstract base class for an etcd node.

		@parent: The node's parent
		@name: the node's name (without path)
		@seq: modification seqno from etcd, to reject old updates

		All mthods have a leading underscore, which is necessary because
		non-underscored names are potential etcd node names.
		"""
	_later_timer = None
	_later_timer_max = None
	_later_max = False
	_later_warned = False
	_env = _NOTGIVEN
	_propagate_updates = None
	is_new = True # for monitors: False after the first call to has_update()
	busy = None

	@classmethod
	async def _new(cls, parent=None, conn=None, key=None, pre=None,recursive=None, typ=None, **kw):
		"""\
			This classmethod loads data (if necessary) and creates a class from a base.

			If @parent is not given, load a root class from @conn and @key.
			Otherwise @key is the path to the child node; the class is
			looked up via the parent's .subtype() method.

			If @recursive is True, @pre needs to have been recursively
			fetched from etcd.
			"""
		kw['_no_update_parent'] = True
		#logger.debug("_new %d %s %s",id(parent),parent,key)
		irec = recursive
		if pre is not None:
			kw['pre'] = pre
		else:
			assert key is not None
		if key is None:
			key = (parent.path if parent else ())+(pre.name,)
		elif isinstance(key,tuple):
			if key:
				name = key[-1]
			else:
				name = ""
		else:
			name = key.rsplit('/',1)[-1]

		if conn is None:
			assert name
			assert parent is not None, "specify conn or parent"
			conn = parent._root()._conn
			kw['parent'] = parent
			cls_getter = lambda: typ if typ is not None else parent.subtype(name, pre=pre,recursive=recursive, raw=False)
			if isinstance(key,str):
				key = parent.path+(name,)
		else:
			assert parent is None, "specify either conn or parent, not both"
			cls_getter = lambda: cls
			kw['conn'] = conn
			kw['key'] = key

		async def get_cls():
			cls = cls_getter()
			cls = await cls.this_obj(recursive=recursive, **kw)
			return cls

		self = None
		try:
			try:
				if recursive and not pre:
					raise ReloadRecursive
				try:
					self = await get_cls()
				except ReloadData:
					assert pre is None
					kw['pre'] = pre = await conn.read(key)
					recursive = False
					self = await get_cls()
					# This way, if determining the class requires
					# recursive content, we do not read twice
				if pre is None:
					kw['pre'] = pre = await conn.read(key)
				if pre.dir:
					await self._fill_data(pre=pre,recursive=irec)
			except ReloadRecursive:
				kw['pre'] = pre = await conn.read(key, recursive=True)
				recursive = True
				if self is None:
					self = await get_cls()
				if pre.dir:
					await self._fill_data(pre=pre,recursive=True)
		except EtcdKeyNotFound:
			raise KeyError(key) from None

		await self.init()
		self._update_parent()
		return self

	def __init__(self, pre=None, name=None,parent=None, _no_update_parent=False, _fill=None, **kw):
		super().__init__(**kw)

		if parent is not None:
			self._parent = weakref.ref(parent)
			self._loop = parent._loop
			self._root = parent._root
			if name is not None:
				if pre is not None:
					assert pre.name == name
			else:
				if pre is None:
					raise ReloadData
				name = pre.name
			self.name = name
			if self._propagate_updates is None:
				self._propagate_updates = (self.name[0] != ':')
			self.path = parent.path+(name,)
			if not _no_update_parent:
				self._update_parent()
			self._lock = asyncio.Lock(loop=self._loop)
		else:
			# This is a root node
			self._root = weakref.ref(self)

		if pre is not None:
			self._seq = pre.modifiedIndex
			self._cseq = pre.createdIndex
			self._ttl = pre.ttl
		self._timestamp = time.time()
		self._later_mon = weakref.WeakValueDictionary()
		self._ready = asyncio.Event(loop=self._loop)
		self._ready_not = True

		if _fill is not None:
			rs = weakref.ref(self)
			for k,v in getattr(_fill,'_data',{}).items():
				if k not in self._data and type(v) is EtcAwaiter:
					self._data[k] = v
					v._parent = rs
			_fill._done = self
			self._later_mon.update(_fill._later_mon)

		#logger.debug("init %d %s",id(self),self)

	def _update_parent(self):
		if self._parent is None:
			return # root
		parent = self._parent()
		name = self.name
		x = parent._data.get(name,None)
		updlogger.debug("%d:run %s add %s %s",self.root._debug_id if self.root else 0, parent, name, x if x is not None else "NEW")

		if x is not None:
			assert not isinstance(self,EtcAwaiter)
			if x is self:
				return
			assert isinstance(x,EtcAwaiter), (id(self),self,"vs.",id(x),x)
		elif hasattr(parent,'_added'):
			parent._added.add(name)
		parent._data[name] = self

		if not self._propagate_updates:
			assert self._propagate_updates is False # "None" would be an error
			parent.updated(seq=self._seq)
		# else: the update happens after my update handler is done

	def throw_away(self):
		"""Delete this node, replacing it with an EtcAwaiter.
			You need to make sure not to retain *any* references to the
			node."""
		p = self.parent
		if p is not None:
			del p._data[self.name]
		self._parent = None
		return EtcAwaiter(p, name=self.name)
		
	@classmethod
	async def this_obj(cls,recursive, **kw):
		"""A method to intercept class creation."""
		return cls(**kw)

	async def _fill_data(self,pre,recursive):
		"""Copy result data to the object. This may require re-reading recursively."""
		# Collect all names to be added, process highest-priority items first
		todo = {}
		for c in pre.child_nodes:
			todo[c.name]=c
		while todo:
			pri = None
			current = {}
			for n,c in todo.items():
				try:
					t = self.subtype(n,dir=c.dir,pre=(c if recursive or not c.dir else None),recursive=recursive, raw=True)
				except ReloadData:
					c = await self.root._conn.read(self.path+(n,))
					t = self.subtype(n,dir=c.dir,pre=c, recursive=False, raw=True)
				if pri is None or t.pri > pri:
					pri = t.pri
					current = {}
				elif t.pri < pri:
					continue
				current[n] = (t,c)
			for n,tc in current.items():
				t,c = tc
				if n not in self._data:
					EtcAwaiter(parent=self,pre=c,name=n)
				self._added.add(n)
			for n,tc in current.items():
				t,c = tc
				del todo[n]
				if c.dir and recursive is None:
					pass
				else:
					a = self._data[n]
					if isinstance(a,EtcAwaiter):
						await a.load(pre=(c if recursive or not c.dir else None), recursive=recursive)
			if todo:
				await self._run_update_step()

		if recursive:
			for k,v in list(self._data.items()):
				if isinstance(v,EtcAwaiter):
					del self._data[k]
		
	async def init(self):
		"""Last step after loading.
			Do things like querying the remote system here."""
		self.updated(seq=0)

	def __hash__(self):
		return hash(self.path)

	def __await__(self):
		"Nodes which are already loaded support lazy lookup by doing nothing."
		yield
		return self

	def _ext_load(self, **k):
		return self.root.task(self.load,**k)

	async def load(self, recursive=None, pre=None):
		"Loader stub for code that's too lazy for testing. Do nothing."
		return self

	@property
	def parent(self):
		p = self._parent
		return None if p is None else p()

	@property
	def root(self):
		return self._root()

	@property
	def env(self):
		return self.root.env

	def task(self,p,*a,**k):
		"""Enqueue an async job to run controlled by this tree"""
		return self.root.task(p,*a,**k)

	async def wait(self, *a,**kw):
		r = self.root
		if r is not None:
			return await r.wait(*a,**kw)

	@property
	def _ready_p(self):
		return 'R' if self._ready.is_set() else 'r' if self._ready_not else 'nr'

	@property
	def _path(self):
		return self.__class__.__name__+":"+"/".join(x for x in self.path)

	def __reduce__(self):
		return EtcNull,(self.__class__.__module__+'.'+self.__class__.__name__,),{'path':self.path}

	def __repr__(self): ## pragma: no cover
		try:
			return "<{} @{}>".format(self.__class__.__name__,'/'.join(self.path))
		except Exception as e:
			logger.exception(e)
			res = super().__repr__()
			return res[:-1]+" ?? "+res[-1]

	def _get_ttl(self):
		if self._ttl is None:
			return None
		return self._ttl - (time.time()-self._timestamp)
	def _set_ttl(self,ttl):
		kw = {}
		if not self._is_dir:
			kw['index'] = self._seq
		self.root.task(self.root._set,self.path,self._dump(self._value), ttl=ttl, dir=self._is_dir, create=False, _die=True, **kw)
	def _del_ttl(self):
		self._set_ttl('')
	ttl = property(_get_ttl, _set_ttl, _del_ttl)

	async def set_ttl(self, ttl, sync=True):
		"""Coroutine to set/update this node's TTL"""
		root=self.root
		kw = {}
		if not self._is_dir:
			kw['index'] = self._seq
		r = await root._set(self.path,self._dump(self._value), ttl=ttl, dir=self._is_dir, create=False, **kw)
		r = r.modifiedIndex
		if sync:
			await root.wait(r)
		return r

	async def del_ttl(self, sync=True):
		return (await self.set_ttl('', sync=True))

	async def has_update(self):
		"""\
			Override this method to get notified after the value changes
			(or that of a child node).

			The call is delayed to allow multiple changes to coalesce.
			When first called, .is_new is True.
			If .is_new is None, the node is being deleted.
			"""
		pass

	def force_updated(self):
		"""Force updating ASAP. Returns a Future. Do not call from .init()"""
		root = self.root
		if root is None:
			return
		updlogger.debug("%d:Force %s",root._debug_id, self)
		return self.task(self._run_update_base)

	@property
	def ready(self):
		"""An awaitable that triggers when no update calls are pending"""
		return self._ready.wait()

	@property
	def is_ready(self):
		"""A flag indicating that no update calls are pending"""
		return self._ready.is_set()

	def updated(self, seq=None):
		"""\
			This node has been updated.
			Schedule a call to the update monitors.
			"""
		r = self.root
		if r is None:
			return
		updlogger.debug("%d:updated %s seq %s rdy %s prop %s",r._debug_id,self,seq,self._ready_p,self._propagate_updates)

		p = self
		while p._propagate_updates and p is not r:
			if not p._ready_not and not p._ready.is_set():
				updlogger.debug("%d:waiting %s",r._debug_id,p)
				return
			p._ready.clear()
			p._ready_not = False
			p = p.parent
		p._queue_update()

	## Update handler: Timeouts.
	#
	# - Initial state: _tag is zero, _timer and _maxtimer are None.
	# - Starting timer: _tag >0, _timer started, _maxtimer started.
	# - Restarting timer: _tag left alone, _timer cancelled and restarted.
	# - Timer triggers: queues update, clears _timer and _tag.
	# - Restarting timer: _tag updated, _timer started.
	# - Queued update: notes that the tag has changed, doesn't run.

	def _queue_update(self):
		updlogger.debug("%d:queue %s",self.root._debug_id if self.root else 0, self)
		self._ready.clear()
		if self._later_max:
			return
		if self._later_timer is None or self._later_tag > 0:
			global _later_tag
			self._later_tag = _later_tag
			_later_tag += 1

		try:
			delay = self.update_delay
			max_delay = self.max_update_delay
			if max_delay < 3*delay:
				max_delay = 3*delay
		except AttributeError:
			# this happens when the root has gone away. Exit.
			return
		if self._later_timer is not None:
			self._later_timer.cancel()
		self._later_timer = self._loop.call_later(delay, self._run_update_reg, self._later_tag)

		if self._later_timer_max is None:
			self._later_timer_max = self._loop.call_later(max_delay, self._run_update_max)
	
	def _run_update_reg(self, tag):
		self._later_timer = None

		root = self.root
		if root is None or root.closed:
			return
		updlogger.debug("%d:start %s",root._debug_id,self)
		root.task(self._run_update, tag, _die=True)

	def _run_update_max(self):
		self._later_timer_max = None

		root = self.root
		if root is None or root.closed:
			return
		(updlogger.info if self._later_warned else updlogger.warn) \
			("%d:start_max %s %d %d",root._debug_id, self, self.update_delay,self.max_update_delay)
		if self._later_timer is not None:
			self._later_timer.cancel()
			self._later_timer = None
		self._later_warned = True
		self._later_tag = 0
		self._later_max = True
		root.task(self._run_update,0, _die=True)

	async def _run_update(self, tag):
		updlogger.debug("%d:upd %s %s %d/%d",self.root._debug_id, self, self._later_max, tag,self._later_tag)
		if self._later_max:
			if tag > 0: # overridden update
				return
		else:
			assert tag > 0
			if self._later_tag != 0 and self._later_tag != tag:
				# A change arrived before this could execute. Retry.
				return
		updlogger.debug("%d:Base %s",self.root._debug_id, self)
		await self._run_update_base()

	async def _run_update_base(self):
		# clear subsequently-queued timers
		if not self._propagate_updates:
			self._later_tag = 0
			self._later_max = False
			if self._later_timer is not None:
				self._later_timer.cancel()
				self._later_timer = None
			if self._later_timer_max is not None:
				self._later_timer_max.cancel()
				self._later_timer_max = None
		await self._run_update_step()
	
	async def _run_update_step(self):
		updlogger.debug("%d:Step %s %s",self.root._debug_id, self, not self._ready.is_set())
		if self._ready.is_set():
			return
		vd = getattr(self,'_data',None)
		if vd:
			again = True
			while again:
				again = False
				for v in list(vd.values()):
					if not v._ready.is_set():
						again = True
						await v._run_update_step()
		self._ready.set()
		try:
			await self._call_monitors()
		except Exception as exc:
			updlogger.debug("%d:Exc %s",self.root._debug_id, self, exc_info=exc)
			await self.root._err_q.put(exc)

	async def _call_monitors(self):
		"""\
			Actually run the monitoring code.

			Exceptions get propagated. They will kill the watcher."""
		try:
			updlogger.debug("%d:has_ %s",self.root._debug_id, self)
			await self.has_update()
			if self._later_mon:
				for f in list(self._later_mon.values()):
					updlogger.debug("%d:mon %s %s",self.root._debug_id, self,f)
					res = f(self)
					try:
						await res
					except TypeError:
						pass
		finally:
			updlogger.debug("%d:done %s",self.root._debug_id, self)
			if self.is_new:
				self.is_new = False

	def add_monitor(self, callback):
		"""\
			Add a monitor function that watches for updates of this node
			(and its children).

			Called with the node as single parameter.
			If .is_new is True, the node is new.
			If .is_new is None, the node is being deleted.
			Otherwise it has been updated.
			(Or at least one of its children, if it's a directory.)
			"""
		global _later_idx
		i,_later_idx = _later_idx,_later_idx+1
		self._later_mon[i] = mon = MonitorCallback(self,i,callback)
		updlogger.debug("%d:add_mon %s %s %s",self.root._debug_id,self,i,callback)
		return mon

	def remove_monitor(self, token):
		if self.root is None:
			return
		updlogger.debug("%d:del_mon %s %s",self.root._debug_id,self,token)
		if isinstance(token,MonitorCallback):
			token = token.i
		self._later_mon.pop(token,None)

	async def _deleted(self):
		#logger.debug("DELETE %s",self.path)
		s = self._seq
		if not self.is_new:
			self.is_new = None
			await self._call_monitors()
		else: # just for safety (and debugging)'s sake
			self.is_new = None # pragma: no cover
		self._ready.set() # sort of
		p = self._parent
		if p is None:
			return # pragma: no cover
		p = p()
		if p is None:
			return # pragma: no cover
		updlogger.debug("%d:deleted: %s",self.root._debug_id,self)

		p.updated(seq=s)

	async def _ext_delete(self, seq=None):
		#logger.debug("DELETE_ %s",self.path)
		if seq is not None:
			self._seq = seq
		p = self._parent
		if p is None:
			return # pragma: no cover
		p = p()
		if p is None:
			return # pragma: no cover
		await p._do_del_node(self)

	async def _ext_update(self,pre):
		#logger.debug("UPDATE %s",self.path)
		if pre.createdIndex is not None:
			if self._cseq is None:
				self._cseq = pre.createdIndex
			elif self._cseq != pre.createdIndex:
				if self._cseq > pre.createdIndex: # pragma: no cover # can't be forced
					logger.info("%d:Create late %s: know %d, get %d", self.root._debug_id, self,self._cseq,pre.createdIndex)
					return
				# this happens if a parent gets deleted and re-created
				logger.debug("%d:Re-created %s: %s %s",self.root._debug_id, self, self._cseq,pre.createdIndex)
				if hasattr(self,'_data'):
					for d in list(self._data.values()):
						await d._ext_delete()
		if pre.modifiedIndex:
			# This can happen when we read a node (e.g. via EtcAwaiter)
			# before the create or update arrives via our watcher.
			if self._seq and self._seq > pre.modifiedIndex: # pragma: no cover # can't be forced
				logger.info("%d:Update late %s know %d, get %d", self.root._debug_id, self, self._seq,pre.modifiedIndex)
			if self._seq and self._seq >= pre.modifiedIndex: # pragma: no cover # ditto
				# already up-to-date: ignore
				return
			self._seq = pre.modifiedIndex
		self._ttl = pre.ttl
		self.updated(seq=pre.modifiedIndex)
		return True

##############################################################################

def _make_name(_name,name):
	if isinstance(name,str):
		name = name.split('/')
	if len(_name) == 1:
		_name = _name[0]
		if isinstance(_name,str):
			_name = _name.split('/')
	return _name if type(name) is bool else tuple(chain(_name,name))

class _EtcDir(EtcBase):
	def lookup(self, *_name, name=()):
		"""\
			Utility function to find a sub-node.
			Like .subdir, but synchronous and can't create anything.

			@_name and @name are chained. A boolean @name is ignored,
			for compatibility with some tagging schemes.
			"""
		name = _make_name(_name,name)

		for n in name:
			self = self._get(n)
		return self

	async def subdir(self, *_name, name=(), create=None, recursive=None):
		"""\
			Utility function to find/create a sub-node.
			@recursive decides what to do if the node thus encountered
			hasn't been loaded before.

			@_name and @name are chained. A boolean @name is ignored,
			for compatibility with some tagging schemes.
			"""
		root=self.root
		try:
			d = self.lookup(*_name, name=name)
		except KeyError as e:
			n = self.path + _make_name(_name,name)
		else:
			if isinstance(d,EtcAwaiter):
				try:
					d = await d
				except (KeyError,etcd.EtcdKeyNotFound):
					pass
			if not isinstance(d,EtcAwaiter):
				if create is True:
					raise etcd.EtcdAlreadyExist(d.path)
				return d
			n = d.path

		if create is False:
			raise KeyError(n)
		logger.debug("NEW %s",n)
		try:
			pre = await root._set(n, prevExist=False, dir=True, value=None)
		except etcd.EtcdAlreadyExist: # pragma: no cover ## timing
			pre = await root._conn.get(n)
		await root.wait(pre.modifiedIndex)
		return await self.lookup(*_name, name=name)

	async def delete(self, key=_NOTGIVEN, sync=True, recursive=None, **kw):
		"""\
			Delete a node.
			Recursive=True: drop it sequentially
			Recursive=False: don't do anything if I have sub-nodes
			Recursive=None(default): let etcd handle it
			"""
		root = self.root
		if key is not _NOTGIVEN:
			res = self._data[key]
			r = await res.delete(sync=sync,recursive=recursive, **kw)
			return r
		if isinstance(self,EtcAwaiter):
			p = self.parent
			if isinstance(p._data.get(self.name,None), EtcAwaiter):
				del p._data[self.name]
		elif recursive:
			for v in list(self._data.values()):
				if not isinstance(v,EtcAwaiter):
					await v.delete(sync=sync,recursive=recursive)
		r = await root._delete(self.path, dir=True, recursive=(recursive is not False))
		r = r.modifiedIndex
		if sync and root is not None:
			await root.wait(r)
		return r

class EtcAwaiter(_EtcDir):
	"""\
		A node that needs to be looked up via "await".

		This implements lazy lookup.

		Note that an EtcAwaiter is a placeholder for a directory node.
		However, a nested EtcAwaiter might actually be a value, so this code
		accepts that.
		"""
	_done = None

	def __new__(cls,parent,pre=None,name=None):
		self = parent._data.get(name,_NOTGIVEN)
		if self is _NOTGIVEN:
			self = object.__new__(cls)
			super().__init__(self, parent=parent,pre=pre,name=name,_no_update_parent=True)
			self._data = {}
			assert name not in parent._data
			parent._data[name] = self
		return self

	def __init__(self,parent,pre=None,name=None):
		pass

	async def _deleted(self):
		"""no-op, can't hook an EtcAwaiter"""
		pass

	def throw_away(self):
		"""no-op"""
		return self

	def __getitem__(self,key):
		v = self._data.get(key,_NOTGIVEN)
		if v is _NOTGIVEN:
			v = EtcAwaiter(self, name=key)
		else:
			assert isinstance(v,EtcAwaiter)
		return v
	_get = __getitem__

	def __len__(self):
		raise RuntimeError("You need to await on %s first" % (str(self),))
	def __contains__(self,key):
		raise RuntimeError("You need to await on %s first" % (str(self),))

	def __await__(self):
		return self.load().__await__()

	async def load(self,recursive=None, pre=None):
		if self._done is not None:
			return self._done # pragma: no cover ## concurrency
		root = self.root
		if root is None:
			return None # pragma: no cover
		try:
			p = self.parent
			if p is None:
				p = await self.root.lookup(*self.path[:-1])
				# This can happen when an awaiter's parent does not exist
				# but it is resolved twice.
			if type(p) is EtcAwaiter:
				p = await p
			async with p._lock:
				if self._done is not None:
					return self._done
				r = p._data.get(self.name,self)
				if type(r) is not EtcAwaiter:
					self._done = r
					return r
				# _fill carries over any monitors and existing EtcAwaiter children
				
				obj = await p._new(parent=p,key=self.name,recursive=recursive, pre=pre, _fill=self)
		except (KeyError,etcd.EtcdKeyNotFound):
			del p._data[self.name]
			raise
		assert self._done is obj
		assert p._data[self.name] is obj, (p._data[self.name],obj)
		return obj

	async def _do_del_node(self, child):
		"""Called by the child to tell us that it vanished"""
		self._data.pop(child.name)

##############################################################################

class EtcXValue(EtcBase):
	"""A value node, i.e. the leaves of the etcd tree."""
	type = str
	_is_dir = False

	_seq = None
	def __init__(self, pre=None,**kw):
		super().__init__(pre=pre, **kw)
		self._value = self._load(pre.value)
		self.updated(0)

	def __hash__(self):
		return hash(self.path)

	# used for testing
	def __eq__(self, other):
		if type(self) != type(other):
			return False # pragma: no cover
		return self.value == other.value

	@classmethod
	def _load(cls,value):
		return cls.type(value)
	@classmethod
	def _dump(cls,value):
		return str(value)

	def _get_value(self):
		# TODO: no cover
		if self._value is _NOTGIVEN: # pragma: no cover
			raise RuntimeError("You did not sync")
		return self._value

	def _set_value(self,value):
		self.root.task(self._do_set,self._dump(value), _die=True)
	async def _do_set(self,value):
		await self.root._set(self.path,value, index=self._seq)

	def _del_value(self):
		self.root.task(self._do_del, _die=True)
	async def _do_del(self):
		await self.root._delete(self.path, index=self._seq)

	value = property(_get_value, _set_value, _del_value)
	__delitem__ = _del_value # for EtcDir.delete

	async def set(self, value, sync=True, ttl=None, ext=False, force=False):
		root = self.root
		if root is None:
			return # pragma: no cover
		if ext:
			self._load(value)
		else:
			assert isinstance(value,self.type), (value,self.type, '/'.join(self.path))
		if not ext:
			if not force and self.value is not None and value == self.value:
				return
			value = self._dump(value)

		r = await root._set(self.path, value, index=None if force else self._seq, ttl=ttl)

		r = r.modifiedIndex
		if sync:
			await root.wait(r)
		return r

	async def delete(self, sync=True, recursive=None, force=False, **kw):
		root = self.root
		if root is None:
			return # pragma: no cover
		r = await root._delete(self.path, index=None if force else self._seq, **kw)
		r = r.modifiedIndex
		if sync:
			await root.wait(r)
		return r

	async def _ext_update(self, pre):
		"""\
			An updated value arrives.
			(It may be late.)
			"""
		if not (await super()._ext_update(pre)): # pragma: no cover
			return
		self._value = self._load(pre.value)

	def __reduce__(self):
		res = super().__reduce__()
		res[2]['value'] = self.value
		return res

	def __repr__(self): ## pragma: no cover
		try:
			return "<{} @{}:{} ={}>".format(self.__class__.__name__,'/'.join(self.path), self._seq, repr(self._value))
		except AttributeError:
			return "<{} @{}:{} ?>".format(self.__class__.__name__,'/'.join(self.path), self._seq)
		except Exception as e:
			logger.exception(e)
			res = super().__repr__()
			return res[:-1]+" ?? "+res[-1]

class EtcValue(EtcXValue):
	# the result of lookups will be auto-dereferenced
	# this class exists so that "interesting" subclasses are more usable
	pass

EtcString = EtcValue
class EtcInteger(EtcValue):
	type = int

class EtcFloat(EtcValue):
	type = float

class EtcBoolean(EtcValue):
	"""A Boolean which writes itself to etcd as number (0 or 1)"""
	type = bool
	values = ('false','true')

	@classmethod
	def _load(cls,value):
		try:
			return cls.type(int(value))
		except ValueError:
			value = value.lower()
			if value in ('true','on',cls.values[1]):
				return True
			if value in ('false','off',cls.values[0]):
				return False
			raise

	@classmethod
	def _dump(cls,value):
		return str(int(value))

class EtcBooleanS(EtcBoolean):
	"""A Boolean which writes itself to etcd as string (self.values)"""
	@classmethod
	def _dump(cls,value):
		return cls.values[value]

##############################################################################

class EtcDir(_EtcDir, MutableMapping):
	"""\
		A node with other nodes below it.

		Map lookup will return a leaf node's EtcValue node.
		Access by attribute will return the value directly.
		"""
	_value = None
	_is_dir = True
	update_delay = 1
	max_update_delay = 5
	added = ()
	deleted = ()

	def __init__(self, value=None, update_delay=None, max_update_delay=None, **kw):
		assert value is None
		if update_delay is not None:
			self.update_delay = update_delay
		if max_update_delay is not None:
			self.max_update_delay = max_update_delay
		self._data = {}
		self._added = set()
		self._deled = set()
		super().__init__(**kw)
		if self._types_from_parent is None:
			self._types_from_parent = (self.name and self.name[0] != ':')

	def __iter__(self):
		return iter(self._data.keys())

	def __len__(self):
		return len(self._data)

	@classmethod
	def _load(cls,value): # pragma: no cover
		assert value is None
		return None
	@classmethod
	def _dump(cls,value): # pragma: no cover
		assert value is None, value
		return None

	def keys(self):
		return self._data.keys()
	def values(self):
		for v in list(self._data.values()):
			if isinstance(v,EtcValue):
				v = v.value
			yield v
	def items(self):
		for k,v in list(self._data.items()):
			if k not in self:
				continue # pragma: no cover ## possible race condition
			if isinstance(v,EtcValue):
				v = v.value
			yield k,v

	_keys = keys
	@property
	def _items(self):
		return self._data.items
	@property
	def _values(self):
		return self._data.values

	def _get(self,key,default=_NOTGIVEN):
		if default is _NOTGIVEN:
			try:
				return self._data[key]
			except KeyError:
				raise KeyError(self.path+(key,)) from None
		else:
			return self._data.get(key,default)

	def get(self,key,default=_NOTGIVEN):
		v = self._get(key,default)
		if isinstance(v,EtcValue):
			v = v.value
		return v
	__getitem__ = get

	def add_monitor(self, callback):
		res = super().add_monitor(callback)
		if self._ready.is_set():
			self.added = set(self._data.keys())
			self.deleted = set()
			callback(self)
		return res

	async def _call_monitors(self):
		self.added,self._added = self._added,set()
		self.deleted,self._deled = self._deled,set()
		updlogger.debug("%d:CALL_MON %s add:%s del:%s",self.root._debug_id,self,self.added,self.deleted)

		await super()._call_monitors()

	def tagged(self, tag=True, depth=0):
		"""\
			async generator to recursively find all sub-nodes with a specific tag
			(or any tag)
			"""
		return _tagged_iter(self,tag, depth=depth)

	def __contains__(self,key):
		return key in self._data

	def __setitem__(self, key,val):
		"""\
			Update a node.
			This just tells etcd to update the value.
			The actual update happens when the watcher sees it.

			If @value is a mapping, recursively add/update values.
			No nodes are deleted!

			Setting an atomic value to a dict, or vice versa, is not
			supported; you need to explicitly delete the conflicting entry
			first.

			@key=None is not supported.
			"""
		try:
			res = self._data[key]
		except KeyError:
			# new node. Send a "set" command for the data item.
			# (or items, if it's a dict)
			root = self.root
			def t_set(path,key,val):
				path += (key,)

				if isinstance(val,dict):
					root.task(root._set,self.path+path, None, prevExist=False, dir=True, _die=True)
					for k,v in val.items():
						t_set(path,k,v)
				else:
					t = self.subtype(path, dir=False, raw=False)
					root.task(self._task_set,path, t._dump(val), _die=True)
			t_set((),key, val)
		else:
			if isinstance(res,EtcXValue):
				if isinstance(val,dict):
					raise ValueError("Cannot replace a terminal node with a mapping",self.path)
				res.value = val
			else:
				if not isinstance(val,dict):
					raise ValueError("Cannot replace a mapping with a terminal node",self.path)
				for k,v in val.items():
					res[k] = v

	async def _task_set(self, path,val):
		#for p in path[:-1]:
			#self = self[p]
		#self = await self # in case it's an EtcAwaiter
		res = await self.root._set(self.path+path, val)
		#res = await self.set(path[-1], val, sync=False, ext=True)
		return res

	async def set(self, key,value, sync=True, replace=True, ext=False, force=False, **kw):
		"""\
			Update a node. This is the coroutine version of assignment.
			Returns the operation's modification index.

			If @key is None, this code will do an etcd "append" operation
			and the return value will be a key,modIndex tuple.

			If @value is a mapping, recursively add/update values.
			No nodes are deleted! Set "replace" to False if you only want
			to supply defaults.

			If @ext is set, the value passed is a string as seen by etcd.
			This is used from the command line.

			Setting an atomic value to a dict, or vice versa, is not
			supported; you need to explicitly delete the conflicting entry
			first.
			"""
		root = self.root
		res = mod = None
		if key is not None and '/' in key:
			key = tuple(k for k in key.split('/') if k != "")
		if isinstance(key,(tuple,list)):
			self = await self.subdir(key[:-1])
			key = key[-1]
		try:
			if key is None:
				raise KeyError
			else:
				sub = self._data[key]
		except KeyError:
			# new node. Send a "set" command for the data item.
			# (or items if it's a dict)
			async def t_set(path,keypath,key,value):
				path += (key,)

				mod = None
				if isinstance(value,dict):
					if value:
						for k,v in value.items():
							r = await t_set(path,keypath,k,v)
							if r is not None:
								mod = r
					else: # empty dict
						r = await root._set(path, None, dir=True, **kw)
						mod = r.modifiedIndex
				else:
					t = self.subtype(*path[keypath:], dir=False, raw=False)
					if ext:
						t._load(value) # raises an error if wrong
					else:
						if type(value) is int and t.type is float:
							pass
						else:
							assert isinstance(value,t.type), (value,t.type, '/'.join(path))
					r = await root._set(path, value if ext else t._dump(value), **kw)
					mod = r.modifiedIndex
				return mod
			if key is None:
				if isinstance(value,dict):
					r = await root._set(self.path, None, append=True, dir=True)
					res = r.key.rsplit('/',1)[1]
					mod = await t_set(self.path,len(self.path),res, value)
					if mod is None:
						mod = r.modifiedIndex # pragma: no cover
				else:
					t = self.subtype(('0',), dir=False, raw=False)
					if ext:
						t._load(value) # raises an error if wrong
					else:
						assert isinstance(value,t.type), (value,t.type, '/'.join(self.path))
					r = await root._set(self.path, value if ext else t._dump(value), append=True, **kw)
					res = r.key.rsplit('/',1)[1]
					mod = r.modifiedIndex
				res = res,mod
			else:
				res = mod = await t_set(self.path,len(self.path),key, value)
		else:
			if isinstance(sub,EtcXValue):
				if isinstance(value,dict):
					raise ValueError("Cannot replace a terminal node with a mapping",self.path)
				if replace:
					res = mod = await sub.set(value, ext=ext, force=force, sync=False, **kw)
			else:
				if not isinstance(value,dict):
					raise ValueError("Cannot replace a mapping with a terminal node",self.path)
				for k,v in value.items():
					res = mod = await sub.set(k,v, replace=replace, ext=ext, force=force, sync=False, **kw)

		if sync and mod and root is not None:
			await root.wait(mod)
		return res

	def __delitem__(self, key=_NOTGIVEN):
		"""\
			Delete a node.
			This just tells etcd to delete the key.
			The actual deletion happens when the watcher sees it.

			This will fail if the directory is not empty.
			"""
		if key is not _NOTGIVEN:
			res = self._data[key]
			res.__delitem__()
			return
		self.root.task(self._delitem, _die=True)

	async def _delitem(self):
		await self.root._delete(self.path,dir=True, index=self._seq)

	async def update(self, d1={}, _sync=True, **d2):
		mod = None
		for k,v in chain(d1.items(),d2.items()):
			mod = await self.set(k,v, sync=False)
		if _sync and mod:
			root = self.root
			if root:
				await root.wait(mod)

	def throw_away(self):
		"""Delete this node, replacing it with an EtcAwaiter.
			You need to make sure not to retain *any* references to the
			node."""
		# make sure that any ref there still is, is unuseable
		for v in self._data.values():
			v.throw_away()
		self._data = None
		return super().throw_away()

	async def _ext_delete(self, seq=None):
		"""We vanished. Oh well."""
		for d in list(self._data.values()):
			await d._ext_delete()
		await super()._ext_delete(seq=seq)

	def __hash__(self):
		return hash(self.path)

	# used for testing
	def __eq__(self, other):
		## don't check that, non-leaves might be OK
		#if type(self) != type(other):
		#	return False
		if not hasattr(other,'_data'):
			return False # pragma: no cover
		return self.path == other.path

	async def _ext_update(self,pre):
		"""processed for doing a TTL update"""
		if pre:
			assert pre.value is None, pre
		await super()._ext_update(pre)

	async def _do_del_node(self, child):
		"""Called by the child to tell us that it vanished"""
		node = self._data.pop(child.name)
		self._deled.add(child.name)
		await node._deleted()

	# The following code implements type lookup.

	_types = None
	_types_from_parent = None

	@hybridmethod
	def register(self, *path, cls=None, **kw):
		"""\
			Register a typed lookup for .subtype() to return.

			If @cls is None, return the (possibly newly-allocated)
			EtcTypes object.
			"""
		if '_types' not in vars(self):
			from .etcd import EtcTypes
			self._types = EtcTypes()
			self._types.doc = repr(self)
		if cls is None:
			return self._types.step(*path)
		return self._types.register(*path, cls=cls, **kw)
		
	def subtype(self,*path,dir=None,pre=None,recursive=None, default=True,raw=False):
		"""\
			Decide which type to use for a new entry.
			@path is the path to the sub-entry.
			@pre is the EtcdResult for that location.
			@recursive is True if the data was retrieved
			recursively.

			The default is to look up the path in the _types
			class attribute (use .register() for adding a type);
			if that doesn't work, ask the parent node if
			_types_from_parent is set (this is the default).

			This method is used for looking up value conversions.
			Thus, value types should never depend on non-path data.

			TODO: add a cache with a coalesced _types list.
			"""
		if dir is None:
			if pre is not None:
				dir = pre.dir
			else:
				raise ReloadData
		types = self._types
		if types is not None:
			cls = types.lookup(*path,dir=dir,raw=True)
			if cls is not None and cls.type is not None:
				return cls if raw else cls.type[dir]
		for sup in type(self).mro():
			types = sup.__dict__.get('_types',None)
			if types is None:
				continue
			cls = types.lookup(*path,dir=dir,raw=True)
			if cls is not None and cls.type is not None:
				return cls if raw else cls.type[dir]
		p = self.parent if self._types_from_parent else None
		if p is None:
			if not default:
				return None
			res = EtcDir if dir else EtcValue
			if raw:
				res = DummyType(res)
			return res
		return p.subtype(*((self.name,)+path),dir=dir,pre=pre,recursive=recursive,raw=raw)
	
	@hybridmethod
	def registrations(self):
		"""\
			Enumerate registered types on this. Yields a sequence of (path-as-tuple,type,docstring) tuples.

			Entries attached to the current instance (if not passing a class) are prefixed with a
			"." path element.

			"""
		def show(p,e):
			if e is None:
				return
			if e.type[0] is not None or e.type[1] is not None:
				yield (p,e.type,e.doc)
			for a,b in e.items():
				yield from show(p+(a,),b)

		if not isinstance(self,type):
			yield from show(('.',),getattr(self,'_types',None))
			self = type(self)
		for k in self.__mro__:
			yield from show((),getattr(k,'_types',None))

class DummyType:
	"""This is a stub type encapsulation, suitable for returning a type
		from an overridden .subtype(…, raw=True)"""
	def __init__(self, t, pri=0):
		self.type = t
		self.pri = pri

##############################################################################

class _DummyFuture:
	def done(self):
		return True
	def __await__(self):
		yield
		return False

_DummyFuture = _DummyFuture()

class EtcRoot(EtcDir):
	"""\
		Root node for a (watched) config tree.

		@conn: the connection this is attached to
		@watcher: the watcher that's talking to me
		@types: type lookup
		@path: the subpath from the etcd root to this, if any
		"""
	_parent = None
	name = ''
	_types = None
	last_mod = None
	closed = False
	job_error = None
	_debug_id = 0

	def __init__(self,conn,watcher=None,key=(),types=None, update_delay=None, max_update_delay=None, **kw):
		global debug_id; debug_id+=1
		self._debug_id = debug_id
		self._conn = conn
		self._watcher = watcher
		self.path = key
		self._loop = conn._loop
		self._lock = asyncio.Lock(loop=self._loop)
		self._q = asyncio.Queue(loop=self._loop)
		self._err_q = asyncio.Queue(loop=self._loop)
		self._done = asyncio.Future(loop=self._loop)
		if types is None:
			from .etcd import EtcTypes
			types = EtcTypes()
		self._types = types
		self._env = Env()
		if update_delay is not None:
			self.update_delay = update_delay
		if max_update_delay is not None:
			self.max_update_delay = max_update_delay
		self._conn._trees.add(self)
		super().__init__(**kw)
		self._propagate_updates = False
		self._job = asyncio.ensure_future(self._run(), loop=self._loop)
		runlogger.debug("%d:init %s",self._debug_id,self)

	async def _run(self):
		while True:
			runlogger.debug("%d:wait",self._debug_id)
			r = await self._q.get()
			if r is None:
				runlogger.debug("%d:end",self._debug_id)
				self._done.set_result(None)
				return
			f,p,a,k = r
			try:
				runlogger.debug("%d:run %s %s %s",self._debug_id, p,a,k)
				r = p(*a,**k)
				if f is None:
					r = asyncio.wait_for(r, self.max_update_delay+2*self.update_delay, loop=self._loop)
				try:
					r = await r
				except TypeError as exc:
					if not hasattr(p,"_async_warn"):
						runlogger.warn("%d:Queued call is not async: %s", self._debug_id,p)
						p._async_warn = True
			except Exception as exc:
				if f is None:
					runlogger.exception("%d:Queue error",self._debug_id)
					await self._err_q.put(exc)
				else:
					runlogger.exception("%d:Set error",self._debug_id)
					f.set_exception(exc)
			else:
				runlogger.debug("%d:Result %s",self._debug_id, r)
				if f is not None and not f.cancelled():
					f.set_result(r)

	def task(self, p,*a, _die=False, **k):
		runlogger.debug("%d:Enq %s %s %s",self._debug_id, p,a,k)
		if self.closed:
			raise asyncio.CancelledError
		f = None if _die else asyncio.Future(loop=self._loop)
		self._q.put_nowait((f,p,a,k))

		if f is not None:
			def timer(f):
				if not f.done():
					f.cancel()
			self._loop.call_later(self.max_update_delay+2*self.update_delay, timer,f)
		return f

	@property
	def env(self):
		return self._env

	@property
	def parent(self):
		return None

	@property
	def stopped(self):
		"""Future which triggers if/when this tree does not monitor etcd"""
		if self._watcher is None:
			# yes we're stopped
			f = asyncio.Future(loop=self._loop)
			f.set_result(False)
			return f
		return self._watcher.stopped

	@property
	def running(self):
		"""Flag that tells whether this tree still monitors etcd"""
		return self._watcher is not None and self._watcher.running

	async def close(self):
		logger.debug("%d:Closing %s",self._debug_id,repr(self))
		from .etcd import WatchStopped

		logger.debug("%d:Closing A",self._debug_id)
		try:
			await self.wait(tasks=True)
		except WatchStopped:
			logger.exception("Not Watching")
		logger.debug("%d:Closing B",self._debug_id)
		self.closed = True
		self._q.put_nowait(None)

		w,self._watcher = self._watcher,None
		if w is not None:
			await w.close()
		logger.debug("%d:Closing C",self._debug_id)

		while self._err_q.qsize():
			exc = self._err_q.get_nowait()
			logger.exception("Close: deferred exception", exc_info=exc)

		logger.debug("%d:Closing D",self._debug_id)
		await self._done
		logger.debug("%d:Closing E",self._debug_id)
		self._conn._trees.remove(self)

	async def wait(self, mod=None, tasks=False):
		"""Delay until async processing is complete"""

		logger.debug("%d:DeferWait A %s %s", self._debug_id,mod, tasks)
		if self._err_q.qsize():
			raise self._err_q.get_nowait()

		if tasks:
			async def noop():
				pass
			logger.debug("%d:DeferWait T",self._debug_id)
			await self.task(noop)

		if self._watcher is not None:
			if mod is None:
				mod = self.last_mod
			logger.debug("%d:DeferWait sync",self._debug_id)
			await self._watcher.sync(mod)

		if self._err_q.qsize():
			raise self._err_q.get_nowait()

		logger.debug("%d:DeferWait end %s",self._debug_id,mod)
		return mod

	def __reduce__(self):
		res = super().__reduce__()
		res[2]['debug_id'] = self._debug_id
		res[2]['root'] = self._conn.root
		res[2]['path'] = self.path
		return res

	def __repr__(self): # pragma: no cover
		try:
			return "<{}:{}:{} /{}>".format(self._debug_id,self.__class__.__name__,self._conn.root,'/'.join(self.path))
		except Exception as e:
			logger.exception(e)
			res = super().__repr__()
			return res[:-1]+" ?? "+res[-1]

	def __del__(self):
		self._kill()
	def _kill(self, ignore_q=True):
		logger.debug("%d:Force-Closing %s",self._debug_id,repr(self))
		self.closed = True
		try:
			self._conn._trees.remove(self)
		except KeyError:
			pass
		if not ignore_q and self._q.qsize():
			import pdb;pdb.set_trace()

		w,self._watcher = self._watcher,None
		if w is not None:
			w._kill() # pragma: no cover # as the tests call close()

	async def delete(self, key=_NOTGIVEN, **kw):
		if key is _NOTGIVEN:
			raise RuntimeError("You can't delete the root") # pragma: no cover
		return (await super().delete(key=key, **kw))

	async def _ext_delete(self, seq=None):
		if self._watcher:
			self._watcher.stop(RuntimeError(),"deleted")

	async def _set(self, *a,**k):
		r = await self._conn.set(*a,**k)
		self.last_mod = r.modifiedIndex
		return r

	async def _delete(self, path,*a,**k):
		try:
			r = await self._conn.delete(path,*a,**k)
			self.last_mod = r.modifiedIndex
		except EtcdKeyNotFound:
			raise KeyError(path) from None
		return r

	async def run_with_wait(self, p,*a,**k):
		res = await p(*a,**k)
		if res is not None:
			res = getattr(res,'modifiedIndex',res)
			if isinstance(res,int) and self._watcher is not None:
				await self._watcher.sync(res)

