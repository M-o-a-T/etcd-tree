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
This declares nodes for the basic etcTree structure.
"""

import weakref
import time
import asyncio
from itertools import chain
from collections.abc import MutableMapping
from contextlib import suppress
import aio_etcd as etcd
from etcd import EtcdResult
from functools import wraps
from .util import hybridmethod

__all__ = ('EtcBase','EtcAwaiter','EtcDir','EtcRoot','EtcValue','EtcXValue',
	'EtcString','EtcFloat','EtcInteger',
	'ReloadData','ReloadRecursive',
	)

class _NOTGIVEN:
	pass
_later_idx = 1

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
		assert tag[0] == ':'
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
				if k == self.tag:
					if not self.depth or self.depth == d:
						self.dirs.append(v)
				elif k[0] == ':':
					continue
				elif self.depth and self.depth <= d:
					continue
				elif type(v) is EtcAwaiter:
					self.trees.append((v,d))
				elif isinstance(v,EtcDir):
					self.trees.append((v,d))
		return (await self.dirs.pop())

	def __next__(self):
		while not self.dirs:
			if not self.trees:
				raise StopIteration
			t,d = self.trees.pop()
			d += 1
			for k,v in t.items():
				if k == self.tag:
					if not self.depth or self.depth == d:
						self.dirs.append(v)
				elif k[0] == ':':
					continue
				elif self.depth and self.depth <= d:
					continue
				elif isinstance(v,EtcAwaiter):
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
	notify_seq = None

	_later = 0
	_env = _NOTGIVEN
	_update_delay = None
	is_new = True # for monitors: False after the first call to has_update()

	@classmethod
	async def _new(cls, parent=None, conn=None, key=None, pre=None,recursive=None, _fill=None, **kw):
		"""\
			This classmethod loads data (if necessary) and creates a class from a base.

			If @parent is not given, load a root class from @conn and @key.
			Otherwise @key is the name of the child node; the class is
			looked up via the parent's .subtype() method.

			If @recursive is True, @pre needs to have been recursively
			fetched from etcd.
			"""
		irec = recursive
		if pre is not None:
			kw['pre'] = pre
			if key is None:
				key = pre.name
		else:
			assert key is not None
		if isinstance(key,tuple):
			if key:
				name = key[-1]
			else:
				name = ""
		else:
			try:
				name = key[key.rindex('/')+1:]
			except ValueError:
				name = key
		if conn is None:
			assert key
			assert '/' not in key
			assert parent is not None, "specify conn or parent"
			conn = parent._root()._conn
			kw['parent'] = parent
			cls_getter = lambda: parent.subtype(name, pre=pre,recursive=recursive)
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

		if _fill is not None:
			for k,v in getattr(_fill,'_data',{}).items():
				if k not in self._data and type(v) is EtcAwaiter:
					self._data[k] = v
			self._later_mon.update(_fill._later_mon)
		await self.init()
		return self

	def __init__(self, pre, name=None,parent=None):
		if parent is not None:
			self._parent = weakref.ref(parent)
			self._loop = parent._loop
			self._root = parent._root
			if name is not None:
				if pre is not None:
					assert pre.name == name
			else:
				name = pre.name
			self.name = name
			self.path = parent.path+(name,)
			if name not in parent._data and hasattr(parent,'_added'):
				parent._added.add(name)
			parent._data[name] = self
		else:
			# This is a root node
			self._root = weakref.ref(self)
		if pre is not None:
			self._seq = pre.modifiedIndex
			self._cseq = pre.createdIndex
			self._ttl = pre.ttl
		self._timestamp = time.time()
		self._later_mon = weakref.WeakValueDictionary()

	@classmethod
	async def this_obj(cls,recursive, **kw):
		"""A method to intercept class creation."""
		return cls(**kw)

	async def _fill_data(self,pre,recursive):
		"""Copy result data to the object. This may require re-reading recursively."""
		conn_get = self._root()._conn.get
		for c in pre.child_nodes:
			n = c.name
			if c.dir and recursive is None:
				self._data[n] = a = EtcAwaiter(parent=self,pre=c,name=n)
				self._added.add(n)
			else:
				# TODO: do this in parallel.
				obj = await self._new(parent=self, key=c.name,
					pre=(c if recursive or not c.dir else None),
					recursive=recursive)
		
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

	def _task(self,p,*a,**k):
		self.root._task_do(p,*a,**k)

	async def wait(self,mod=None):
		await self.root.wait(mod=mod)

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
		self._task(self.root._set,self.path,self._dump(self._value), ttl=ttl, dir=self._is_dir, create=False, **kw)
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

	def has_update(self):
		"""\
			Override this method to get notified after the value changes
			(or that of a child node).

			The call is delayed to allow multiple changes to coalesce.
			When first called, .is_new is True.
			If .is_new is None, the node is being deleted.
			"""
		pass

	@property
	def update_delay(self):
		if self._update_delay is None:
			self._update_delay = self.parent.update_delay
		return self._update_delay

	def force_updated(self, _sub=False):
		"""\
			Call all update handlers now.
			"""
		if not self._later:
			return
		if type(self._later) is int:
			# at least one child is blocked, thus run its update handlers
			self._later = False
			for v in self._data.values():
				v.force_updated(_sub=True)
			assert self._later == 0, self._later
		if not isinstance(self._later, int):
			self._later.cancel()
			# will be set to zero in _run_update()
			self._later = 'x'
		self._run_update(_force=_sub)
		assert self._later == 0

	def updated(self, seq=None, _force=False):
		"""\
			Schedule a call to the update monitors.
			@_force: False: schedule a call
			         True: a child node's scheduler is done (INTERNAL)
			"""
		# Invariant: _later is either the number of direct children which
		# are blocked or, if there are none, an asyncio call_later token.
		# (The token has a .cancel method, thus it cannot be an integer.)
		# A node is blocked iff its _later attribute is not zero.
		#
		# Thus, after adding a timer we walk up the parent chain.
		# If the parent is blocked, increment the counter and stop.
		# Otherwise, drop the timer if there is one, set the counter to 1, and continue.
		#
		# After a timer runs, it calls its parent's updated(_force=True),
		# which decrements the counter and adds the timer if that reaches zero.

		#logger.debug("run_update register %s, later is %s. force %s",self.path,self._later,_force)
		p = self._parent
		if self._later:
			# In this block, clear the parent (p) if it was already blocked.
			# Otherwise we'd block it again later, which would be Bad.
			if type(self._later) is int:
				if _force:
					assert self._later > 0
					self._later += -1
					if self._later:
						#logger.debug("run_update still_blocked %s, later is %s",self.path,self._later)
						return
					p = None
				elif self._later > 0:
					#logger.debug("run_update already_blocked %s, later is %s",self.path,self._later)
					return
			else:
				self._later.cancel()
				p = None
		else:
			assert not _force, self._later
		self.notify_seq = seq

		try:
			ud = self.update_delay
		except AttributeError:
			# this happens when the root has gone away. Exit.
			return
		else:
			self._later = self._loop.call_later(self.update_delay,self._run_update)

		while p:
			# Now block our parents, until we find one that's blocked
			# already. In that case we increment its counter and stop.
			p = p()
			if p is None:
				return # pragma: no cover
			#logger.debug("run_update block %s, later was %s",p.path,p._later)
			if type(p._later) is int:
				p._later += 1
				if p._later > 1:
					return
			else:
				# this node has a running timer. By the invariant it cannot
				# have (had) blocked children, therefore trying to unblock it
				# now must be a bug.
				assert not _force
				p._later.cancel()
				# The call will be re-scheduled later, when the node unblocks
				p._later = 1
				return
			p = p._parent

	def _run_update(self, _force=False):
		"""\
			Timer callback to run a node's callback.

			If @force is True, this is called from force_update
			which will update the parent.
		"""
		#logger.debug("run_update %s",self.path)
		p = None
		ls = self.notify_seq
		self._later = 0
		# At this point our parent's invariant is temporarily violated,
		# but we fix that later: if this is the last blocked child and
		# _call_monitors() triggers another update, we'd create and then
		# immediately destroy a timer
		try:
			self._call_monitors()
		except Exception as exc:
			# A monitor died. The tree may be inconsistent.
			root = self.root
			if root is not None:
				root.propagate_exc(exc,self)

		if _force:
			return
		p = self._parent
		if p is None:
			return
		p = p()
		if p is None:
			return # pragma: no cover
		# Now unblock the parent, restoring the invariant.
		p.updated(seq=ls,_force=True)

	def _call_monitors(self):
		"""\
			Actually run the monitoring code.

			Exceptions get propagated. They will kill the watcher."""
		try:
			self.has_update()
			if self._later_mon:
				for f in list(self._later_mon.values()):
					f(self)
		finally:
			if self.is_new:
				self.is_new = False

	def add_monitor(self, callback):
		"""\
			Add a monitor function that watches for updates of this node
			(and its children).

			Called with the node as single parameter.
			If .seq is zero, the node is being deleted.
			"""
		global _later_idx
		i,_later_idx = _later_idx,_later_idx+1
		self._later_mon[i] = mon = MonitorCallback(self,i,callback)
		logger.debug("run_update add_mon %s %s %s",self.path,i,callback)
		return mon

	def remove_monitor(self, token):
		#logger.debug("run_update del_mon %s %s",self.path,token)
		if isinstance(token,MonitorCallback):
			token = token.i
		self._later_mon.pop(token,None)

	def _deleted(self):
		#logger.debug("DELETE %s",self.path)
		s = self._seq
		self._seq = None
		if not self.is_new:
			self.is_new = None
			self._call_monitors()
		else: # just for safety (and debugging)'s sake
			self.is_new = None # pragma: no cover
		if self._later:
			if type(self._later) is not int:
				self._later.cancel()
		p = self._parent
		if p is None:
			return # pragma: no cover
		p = p()
		if p is None:
			return # pragma: no cover
		#logger.debug("run_update: deleted:")

		p.updated(seq=s, _force=bool(self._later))

	def _ext_delete(self, seq=None):
		#logger.debug("DELETE_ %s",self.path)
		p = self._parent
		if p is None:
			return # pragma: no cover
		p = p()
		if p is None:
			return # pragma: no cover
		p._ext_del_node(self)

	def _ext_update(self, pre):
		#logger.debug("UPDATE %s",self.path)
		if pre.createdIndex is not None:
			if self._cseq is None:
				self._cseq = pre.createdIndex
			elif self._cseq != pre.createdIndex:
				# this happens if a parent gets deleted and re-created
				logger.info("Re-created %s: %s %s",self.path, self._cseq,pre.createdIndex)
				if hasattr(self,'_data'):
					for d in list(self._data.values()):
						d._ext_delete()
		if pre.modifiedIndex:
			if self._seq and self._seq > pre.modifiedIndex:
				raise RuntimeError("Updates out of order: saw %d, has %d" % (self._seq,seq)) # pragma: no cover # hopefully
			self._seq = pre.modifiedIndex
		self._ttl = pre.ttl
		self.updated(seq=pre.modifiedIndex)
		return True

##############################################################################

class _EtcDir(EtcBase):
	def lookup(self, *_name, name=()):
		"""\
			Utility function to find a sub-node.
			Like .subdir, but synchronous and can't create anything.
			"""
		if isinstance(name,str):
			name = name.split('/')
		if len(_name) == 1:
			_name = _name[0]
			if isinstance(_name,str):
				_name = _name.split('/')

		for n in chain(_name,name):
			self = self[n]
		return self

class EtcAwaiter(_EtcDir):
	"""\
		A node that needs to be looked up via "await".

		This implements lazy lookup.

		Note that an EtcAwaiter is a placeholder for a directory node.
		However, a nested EtcAwaiter might actually be a value, so this code
		accepts that.
		"""
	_done = None

	def __init__(self,parent,pre=None,name=None):
		super().__init__(parent=parent, pre=pre,name=name)
		self._lock = asyncio.Lock(loop=self._loop)
		self._data = {}

	def __getitem__(self,key):
		v = self._data.get(key,_NOTGIVEN)
		if v is _NOTGIVEN:
			self._data[key] = v = EtcAwaiter(self, name=key)
		return v
	_get = __getitem__

	def __await__(self):
		return self.load(None).__await__()

	async def load(self,recursive=None, pre=None):
		async with self._lock:
			if self._done is not None:
				return self._done # pragma: no cover ## concurrency
			root = self.root
			if root is None:
				return None # pragma: no cover
			p = self.parent
			if p is None:
				p = await self.root.lookup(*self.path[:-1])
				# This can happen when an awaiter's parent does not exist
				# but it is resolved twice.
			elif type(p) is EtcAwaiter:
				p = await p
				r = p._data.get(self.name,self)
				if type(r) is not EtcAwaiter:
					self._done = r
					return r
			# _fill carries over any monitors and existing EtcAwaiter instances
			obj = await p._new(parent=p,key=self.name,recursive=recursive, pre=pre, _fill=self)
			self._done = obj
			assert p._data[self.name] is obj
			return obj

	def _ext_del_node(self, child):
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
		self._task(self.root._set,self.path,self._dump(value), index=self._seq)
	def _del_value(self):
		self._task(self.root._delete,self.path, index=self._seq)
	value = property(_get_value, _set_value, _del_value)
	__delitem__ = _del_value # for EtcDir.delete

	async def set(self, value, sync=True, ttl=None):
		root = self.root
		if root is None:
			return # pragma: no cover
		r = await root._set(self.path,self._dump(value), index=self._seq, ttl=ttl)
		r = r.modifiedIndex
		if sync:
			await root.wait(r)
		return r

	async def delete(self, sync=True, recursive=None, **kw):
		root = self.root
		if root is None:
			return # pragma: no cover
		r = await root._delete(self.path, index=self._seq, **kw)
		r = r.modifiedIndex
		if sync:
			await root.wait(r)
		return r

	def _ext_update(self, pre):
		"""\
			An updated value arrives.
			(It may be late.)
			"""
		if not super()._ext_update(pre): # pragma: no cover
			return
		self._value = self._load(pre.value)

	def __repr__(self): ## pragma: no cover
		try:
			return "<{} @{} ={}>".format(self.__class__.__name__,'/'.join(self.path), repr(self._value))
		except Exception as e:
			logger.exception(e)
			res = super().__repr__()
			return res[:-1]+" ?? "+res[-1]

class EtcValue(EtcXValue):
	# the result of directory lookups will be auto-dereferenced
	# this exists so that "interesting" subclasses are more usable
	pass

EtcString = EtcValue
class EtcInteger(EtcValue):
	type = int
class EtcFloat(EtcValue):
	type = float

##############################################################################

class EtcDir(_EtcDir, MutableMapping):
	"""\
		A node with other nodes below it.

		Map lookup will return a leaf node's EtcValue node.
		Access by attribute will return the value directly.
		"""
	_value = None
	_is_dir = True
	added = ()
	deleted = ()

	def __init__(self, value=None, **kw):
		assert value is None
		self._data = {}
		self._added = set()
		self._deled = set()
		super().__init__(**kw)

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
		assert value is None
		return None

	def keys(self):
		return self._data.keys()
	def values(self):
		for v in self._data.values():
			if isinstance(v,EtcValue):
				v = v.value
			yield v
	def items(self):
		for k,v in self._data.items():
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
				raise KeyError(self.path+(key,))
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
		if self.added and not self._later:
			self.added = set(self._data.keys())
			self.deleted = set()
			callback(self)
		return res

	def _call_monitors(self):
		self.added,self._added = self._added,set()
		self.deleted,self._deled = self._deled,set()
		super()._call_monitors()

	async def subdir(self, *_name, name=(), create=None, recursive=None):
		"""\
			Utility function to find/create a sub-node.
			@recursive decides what to do if the node thus encountered
			hasn't been loaded before.
			"""
		root=self.root

		if isinstance(name,str):
			name = name.split('/')
		if len(_name) == 1:
			_name = _name[0]
			if isinstance(_name,str):
				_name = _name.split('/')

		async def step(n,last=False):
			nonlocal self
			if type(self) is EtcAwaiter:
				self = await self.load(None)
			if last and create and n in self:
				pre = await root._set(self.path+(n,), prevExist=False, dir=True, value=None)
				raise RuntimeError("This should exist")
			elif create is not False and n not in self:
				try:
					pre = await root._set(self.path+(n,), prevExist=False, dir=True, value=None)
				except etcd.EtcdAlreadyExist: # pragma: no cover ## timing
					pre = await root._conn.get(self.path+(n,))
				await root.wait(pre.modifiedIndex)
			self = self[n]
		n = None
		for nn in chain(_name,name):
			if n is not None:
				await step(n)
			n = nn
		if n is not None:
			await step(n,True)

		if isinstance(self,EtcAwaiter):
			self = await self.load(recursive)
		return self

	def tagged(self,tag, depth=0):
		"""async Generator to find all sub-nodes with a tag"""
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
					root._task_do(root._set,self.path+path, None, prevExist=False, dir=True)
					for k,v in val.items():
						t_set(path,k,v)
				else:
					t = self.subtype(path, dir=False)
					root._task_do(self._task_set,path, t._dump(val))
			t_set((),key, val)
		else:
			if isinstance(res,EtcXValue):
				assert not isinstance(val,dict)
				res.value = val
			else:
				assert isinstance(val,dict)
				for k,v in val.items():
					res[k] = v

	async def _task_set(self, path,val):
		for p in path[:-1]:
			self = self[p]
		self = await self # in case it's an EtcAwaiter
		res = await self.set(path[-1], val, sync=False)
		return res

	async def set(self, key,value, sync=True, **kw):
		"""\
			Update a node. This is the coroutine version of assignment.
			Returns the operation's modification index.

			If @key is None, this code will do an etcd "append" operation
			and the return value will be a key,modIndex tuple.

			If @value is a mapping, recursively add/update values.
			No nodes are deleted!

			Setting an atomic value to a dict, or vice versa, is not
			supported; you need to explicitly delete the conflicting entry
			first.
			"""
		root = self.root
		res = mod = None
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
				keypath += 1

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
					t = self.subtype(*path[keypath:], dir=False)
					r = await root._set(path, t._dump(value), prevExist=False, **kw)
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
					t = self.subtype(('0',), dir=False)
					r = await root._set(self.path, t._dump(value), append=True, **kw)
					res = r.key.rsplit('/',1)[1]
					mod = r.modifiedIndex
				res = res,mod
			else:
				res = mod = await t_set(self.path,len(self.path),key, value)
		else:
			if isinstance(sub,EtcXValue):
				assert not isinstance(value,dict)
				res = mod = await sub.set(value, **kw)
			else:
				assert isinstance(value,dict)
				for k,v in value.items():
					res = mod = await sub.set(k,v, **kw)

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
		self._task(self.root._delete,self.path,dir=True, index=self._seq)

	async def update(self, d1={}, _sync=True, **d2):
		mod = None
		for k,v in chain(d1.items(),d2.items()):
			mod = await self.set(k,v, sync=False)
		if _sync and mod:
			root = self.root
			if root:
				await root.wait(mod)

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
			await res.delete(sync=sync,recursive=recursive, **kw)
			return
		if recursive:
			for v in list(self._data.values()):
				await v.delete(sync=sync,recursive=recursive)
		r = await root._delete(self.path, dir=True, recursive=(recursive is None))
		r = r.modifiedIndex
		if sync and root is not None:
			await root.wait(r)
		return r

	def throw_away(self):
		return EtcAwaiter(self.parent,name=self.name)
		
	def _ext_delete(self):
		"""We vanished. Oh well."""
		for d in list(self._data.values()):
			d._ext_delete()
		super()._ext_delete()

	def __hash__(self):
		return hash(self.path)

	# used for testing
	def __eq__(self, other):
		## don't check that, non-leaves might be OK
		#if type(self) != type(other):
		#	return False
		if not hasattr(other,'_data'):
			return False # pragma: no cover
		return self._data == other._data

	def _ext_update(self, pre, **kw):
		"""processed for doing a TTL update"""
		if pre:
			assert pre.value is None
		super()._ext_update(pre=pre, **kw)

	def _ext_del_node(self, child):
		"""Called by the child to tell us that it vanished"""
		self._deled.add(child.name)
		node = self._data.pop(child.name)
		node._deleted()

	# The following code implements type lookup.

	_types = None
	_types_from_parent = True

	@hybridmethod
	def register(self, *path,**kw):
		"""Register a typed lookup."""
		if self._types is None:
			from .etcd import EtcTypes
			self._types = EtcTypes()
		return self._types.register(*path, **kw)
		
	def subtype(self,*path,dir=None,pre=None,recursive=None):
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
			cls = types.lookup(*path,dir=dir)
			if cls is not None:
				return cls
		for sup in type(self).mro():
			types = sup.__dict__.get('_types',None)
			if types is None:
				continue
			cls = types.lookup(*path,dir=dir)
			if cls is not None:
				return cls
		p = self.parent if self._types_from_parent else None
		if p is None:
			return EtcDir if dir else EtcValue
		return p.subtype(*((self.name,)+path),dir=dir,pre=pre,recursive=recursive)
	
##############################################################################

class EtcRoot(EtcDir):
	"""\
		Root node for a (watched) config tree.

		@conn: the connection this is attached to
		@watcher: the watcher that's talking to me
		@types: type lookup
		"""
	_parent = None
	name = ''
	_path = ''
	_types = None
	_update_delay = 1
	_tasks = None
	_task_now = None
	_task_done = None
	last_mod = None

	def __init__(self,conn,watcher=None,key=(),types=None, update_delay=None, **kw):
		self._conn = conn
		self._watcher = watcher
		self.path = key
		self._tasks = []
		self._loop = conn._loop
		if types is None:
			from .etcd import EtcTypes
			types = EtcTypes()
		self._types = types
		self._env = Env()
		if update_delay is not None:
			self._update_delay = update_delay
		super().__init__(**kw)

	@property
	def env(self):
		return self._env

	# Progress of task handling:
	# * _task_done is None.
	# * _task_next() sets _done to a future and runs tasks.
	# * An exception or running out of tasks sets _done to
	#   the exception, or the last result / None.
	# * wait() processed the result and sets _done to None.
	# * repeat as necessary.
	# 
	def _task_next(self,f=None):
		if self._task_done is not None and self._task_done.done():
			# wait for .wait()
			return
		if f is None:
			f = self._task_now
		if self._task_done is None:
			self._task_done = asyncio.Future(loop=self._loop)
		if f is not None:
			if not f.done():
				return
			if f.cancelled():
				self._task_done.cancel()
				self._task_now = None
				return
			exc = f.exception()
			if exc is not None:
				self._task_done.set_exception(exc)
				self._task_now = None
				return
		# 
		if not self._tasks:
			self._task_now = None
			self._task_done.set_result(f.result() if f else None)
			return
		p,a,k = self._tasks.pop(0)
		try:
			self._task_now = asyncio.ensure_future(self.run_with_wait(p,*a,**k), loop=self._loop)
			self._task_now.add_done_callback(self._task_next)
		except Exception as exc:
			self._task_done.set_exception(exc)

	def _task_do(self,p,*a,**k):
		self._tasks.append((p,a,k))
		self._task_next()

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
		w,self._watcher = self._watcher,None
		if w is not None:
			await w.close()

	async def wait(self, mod=None):
		# Here 
		while True:
			if self._task_done is None:
				if not self._tasks and self._task_now is None:
					break
				self._task_next()
				continue
			try:
				await self._task_done
			finally:
				self._task_done = None
		if self._watcher is not None:
			if mod is None:
				mod = self.last_mod
			await self._watcher.sync(mod)

	def __repr__(self): # pragma: no cover
		try:
			return "<{}:{} @{}>".format(self.__class__.__name__,self._conn.root, self.path)
		except Exception as e:
			logger.exception(e)
			res = super().__repr__()
			return res[:-1]+" ?? "+res[-1]

	def __del__(self):
		self._kill()
	def _kill(self):
		if not hasattr(self,'_watcher'):
			return # pragma: no cover
		w,self._watcher = self._watcher,None
		if w is not None:
			w._kill() # pragma: no cover # as the tests call close()

	def delete(self, key=_NOTGIVEN, **kw):
		if key is _NOTGIVEN:
			raise RuntimeError("You can't delete the root") # pragma: no cover
		return super().delete(key=key, **kw)

	def _ext_delete(self):
		if self._watcher:
			self._watcher.stop(RuntimeError(),"deleted")

	def propagate_exc(self, exc,node):
		w = self._watcher
		if w is not None:
			w.stop(exc,node.path)

	async def _set(self, *a,**k):
		r = await self._conn.set(*a,**k)
		self.last_mod = r.modifiedIndex
		return r

	async def _delete(self, *a,**k):
		r = await self._conn.delete(*a,**k)
		self.last_mod = r.modifiedIndex
		return r

	async def run_with_wait(self, p,*a,**k):
		res = await p(*a,**k)
		if res is not None:
			res = getattr(res,'modifiedIndex',res)
			if isinstance(res,int) and self._watcher is not None:
				await self._watcher.sync(res)

