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
import aio_etcd as etcd

class _NOTGIVEN:
	pass
_later_idx = 1

class UnknownNodeError(RuntimeError):
	"""\
		This node does not accept this member.
		"""
	pass

class FrozenError(RuntimeError):
	"""\
		This tree is no longer updated due to an error.
		You cannot access any of its leaf elements any more.
		"""
	pass

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

class mtBase(object):
	"""\
		Abstract base class for an etcd node.

		@parent: The node's parent
		@name: the node's name (without path)
		@seq: modification seqno from etcd, to reject old updates

		All mthods have a leading underscore, which is necessary because
		non-underscored names are potential etcd node names.
		"""
	_later = 0
	_frozen = False
	_env = _NOTGIVEN

	def __init__(self, parent=None, name=None, seq=None, cseq=None, ttl=None):
		if name:
			self._parent = weakref.ref(parent)
			self._loop = parent._loop
			self._root = parent._root
			self.name = name
			self.path = parent.path+'/'+name
			self._keypath = parent._keypath+(name,)
		else:
			# This is a root node
			self._root = weakref.ref(self)
		self._seq = seq
		self._cseq = cseq
		self._ttl = ttl
		self._timestamp = time.time()
		self._later_mon = weakref.WeakValueDictionary()

	async def __await__(self):
		"Nodes which are already loaded support lazy lookup by doing nothing."
		return self

	@property
	def env(self):
		if self._env is _NOTGIVEN:
			self._env = self._root().env
		return self._env

	def _task(self,p,*a,**k):
		f = asyncio.ensure_future(p(*a,**k), loop=self._loop)
		f.args = (self,p,a,k)
		self._root()._tasks.append(f)

	async def wait(self,mod=None,timeout=None):
		await self._root().wait(mod, timeout=timeout)

	def __repr__(self): ## pragma: no cover
		try:
			return "<{} @{}>".format(self.__class__.__name__,self.path)
		except Exception as e:
			logger.exception(e)
			res = super(mtBase,self).__repr__()
			return res[:-1]+" ?? "+res[-1]

	def _get_ttl(self):
		if self._ttl is None:
			return None
		return self._ttl - (time.time()-self._timestamp)
	def _set_ttl(self,ttl):
		kw = {}
		if self._is_dir:
			kw['prev'] = None
		else:
			kw['index'] = self._seq
		self._task(self._root()._conn.set,self.path,self._dump(self._value), ttl=ttl, dir=self._is_dir, **kw)
	def _del_ttl(self):
		self._set_ttl('')
	ttl = property(_get_ttl, _set_ttl, _del_ttl)

	async def set_ttl(self, ttl, sync=True):
		"""Coroutine to set/update this node's TTL"""
		root=self._root()
		kw = {}
		if self._is_dir:
			kw['prev'] = None
		else:
			kw['index'] = self._seq
		r = await root._conn.set(self.path,self._dump(self._value), ttl=ttl, dir=self._is_dir, **kw)
		r = r.modifiedIndex
		if sync:
			await root.wait(r)
		return r

	async def del_ttl(self, sync=True):
		return (await self.set_ttl('', sync=True))

	def _freeze(self):
		self._frozen = True

	def has_update(self):
		"""\
			Override this method to get notified after the value changes
			(or that of a child node).

			The call is delayed to allow multiple changes to coalesce.
			If .seq is None, the node is being deleted.
			"""
		pass

	def updated(self, seq=None, _force=False):
		"""Call to schedule a call to the update monitors.
			@_force: False: schedule a call
				      True: child scheduler is done (DO NOT USE)
			"""
		# Invariant: _later is the number of direct children which are blocked.
		# If that is zero, it may be an asyncio call_later token instead.
		# (The token has a .cancel method, thus it cannot be an integer.)
		# A node is blocked if its _later attribute is not zero.
		#
		# Thus, adding a timer implies walking up the parent chain until we
		# find a node that's already blocked, where we increment the
		# counter (or drop the timer and set the counter to 1) and stop.
		# After a timer runs, it calls its parent's updated(_force=True),
		# which decrements the counter and adds a timer if that reaches zero.

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
			assert not _force
		self._later_seq = seq

		self._later = self._loop.call_later(1,self._run_update)

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
				# have (had) blocked children, therefore trying to unblock this
				# node must be a bug.
				assert not _force
				p._later.cancel()
				# The call will be re-scheduled later, when the node unblocks
				p._later = 1
				return
			p = p._parent

	@property
	def parent(self):
		p = self._parent
		return None if p is None else p()

	def _run_update(self):
		"""Timer callback to run a node's callback."""
		#logger.debug("run_update %s",self.path)
		ls = self._later_seq
		self._later = 0
		# At this point our parent's invariant is temporarily violated,
		# but we fix that later: if this is the last blocked child and
		# _call_monitors() triggers another update, we'd create and then
		# immediately destroy a timer
		self._call_monitors()

		p = self._parent
		if p is None:
			return
		p = p()
		if p is None:
			return # pragma: no cover
		# Now unblock the parent, restoring the invariant.
		p.updated(seq=ls,_force=True)

	def _call_monitors(self):
		"""Actually run the monitoring code."""
		try:
			self.has_update()
		except Exception: # pragma: no cover
			logger.exception("Monitoring %s at %s",lp,ls)
		if self._later_mon:
			for k,f in list(self._later_mon.items()):
				try:
					#logger.debug("run_update %s: call %s",self.path,f)
					f(self)
				except Exception:
					logger.exception("Monitoring %s at %s",f,k)
					del self._later_mon[k]

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
		#logger.debug("run_update add_mon %s %s %s",self.path,i,callback)
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
		self._call_monitors()
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

	def _ext_update(self, seq=None, cseq=None, ttl=_NOTGIVEN):
		#logger.debug("UPDATE %s",self.path)
		if cseq is not None:
			if self._cseq is None:
				self._cseq = cseq
			elif self._cseq != cseq:
				# this happens if a parent directory gets deleted and re-created
				logger.info("Re-created %s",self.path)
				for d in list(self._data.values()):
					d._ext_delete()
		if seq and self._seq and self._seq >= seq:
			raise RuntimeError("Updates out of order") # pragma: no cover # hopefully
		if seq: # pragma: no branch
			self._seq = seq
		if ttl is not _NOTGIVEN: # pragma: no branch
			self._ttl = ttl
		self.updated(seq=seq)
		return True

##############################################################################

class mtAwaiter(mtBase):
	"""\
		A node that needs to be looked up via "await".

		This implements lazy 
		"""
	_done = None

	def __init__(self,parent,name):
		super().__init__(parent=parent, name=name)
		self.parent = lambda: parent # no weakref
		self._data = {}

	def __getitem__(self,key):
		v = self._data.get(key,_NOTGIVEN)
		if v is _NOTGIVEN:
			self._data[key] = v = mtAwaiter(self, name=key)
		return v

	async def __await__(self):
		if self._done is not None:
			return self._done
		root = self._root()
		if root is None:
			return None # pragma: no cover
		p = self.parent()
		if type(p) is mtAwaiter:
			p = await p
		res = await root._conn.get(self.path)
		cls = root._types.lookup(self._keypath+(name,), dir=dir)
		if cls is None:
			cls = mtDir if res.dir else mtValue
		else:
			assert issubclass(cls, mtDir if res.dir else mtValue)
		if dir:
			value = cls._load(res.value)
			obj = cls(parent=p,name=self.name)
			obj._data = self._data
			for c in res.children:
				if c is res:
					continue
				n = c.key
				n = n[n.rindex('/')+1:]
				if n not in obj._data:
					obj._data[n] = mtAwaiter(parent=obj,name=n)
		else:
			obj = cls(parent=p,name=self.name, value=value)
		p._data[self.name] = self._done = obj
		p._later_mon.update(self._later_mon)
		return obj

##############################################################################

class mtValue(mtBase):
	"""A value node, i.e. the leaves of the etcd tree."""
	type = str
	_is_dir = False

	_seq = None
	def __init__(self, value=_NOTGIVEN, **kw):
		super().__init__(**kw)
		self._value = value

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
		if self._frozen: # pragma: no cover
			raise FrozenError(self.path)
		if self._value is _NOTGIVEN: # pragma: no cover
			raise RuntimeError("You did not sync")
		return self._value
	def _set_value(self,value):
		if self._frozen: # pragma: no cover
			raise FrozenError(self.path)
		self._task(self._root()._conn.set,self.path,self._dump(value), index=self._seq)
	def _del_value(self):
		if self._frozen: # pragma: no cover
			raise FrozenError(self.path)
		self._task(self._root()._conn.delete,self.path, index=self._seq)
	value = property(_get_value, _set_value, _del_value)
	__delitem__ = _del_value # for mtDir.delete

	async def set(self, value, sync=True, ttl=None):
		if self._frozen: # pragma: no cover
			raise FrozenError(self.path)
		root = self._root()
		if root is None:
			return # pragma: no cover
		r = await root._conn.set(self.path,self._dump(value), index=self._seq, ttl=ttl)
		r = r.modifiedIndex
		if sync:
			await root.wait(r)
		return r

	async def delete(self, sync=True, recursive=None, **kw):
		if self._frozen: # pragma: no cover
			raise FrozenError(self.path)
		root = self._root()
		if root is None:
			return # pragma: no cover
		r = await root._conn.delete(self.path, index=self._seq, **kw)
		r = r.modifiedIndex
		if sync:
			await root.wait(r)
		return r

	def _ext_update(self, value, **kw):
		"""\
			An updated value arrives.
			(It may be late.)
			"""
		if not super(mtValue,self)._ext_update(**kw): # pragma: no cover
			return
		self._value = self._load(value)

mtString = mtValue
class mtInteger(mtValue):
	type = int
class mtFloat(mtValue):
	type = float

##############################################################################

class mtDir(mtBase, MutableMapping):
	"""\
		A node with other nodes below it.

		If @_final is set, you cannot add unknown entries.
		If true, they also won't be added when the arrive from etcd.

		Map lookup will return a leaf node's mtValue node.
		Access by attribute will return the value directly.
		"""
	_final = None
	_value = None
	_is_dir = True

	def __init__(self, value=None, **kw):
		assert value is None
		super().__init__(**kw)
		self._data = {}

	def __iter__(self):
		return iter(self._data.keys())

	def __len__(self):
		return len(self._data)

	@classmethod
	def _load(cls,value):
		assert value is None
		return None
	@classmethod
	def _dump(cls,value): # pragma: no cover
		assert value is None
		return None

	def _add_awaiter(self, c):
		assert c not in self._data
		self._data[c] = mtAwaiter(self,c)
	def keys(self):
		return self._data.keys()
	def values(self):
		for v in self._data.values():
			if isinstance(v,mtValue):
				v = v.value
			yield v
	def items(self):
		for k,v in self._data.items():
			if isinstance(v,mtValue):
				v = v.value
			yield k,v
	def _get(self,key,default=_NOTGIVEN):
		if default is _NOTGIVEN:
			return self._data[key]
		else:
			return self._data.get(key,default)

	def get(self,key,default=_NOTGIVEN):
		v = self._get(key,default)
		if isinstance(v,mtValue):
			v = v.value
		return v
	__getitem__ = get

	async def subdir(self, *_name, name=(), create=False):
		"""Utility function to find/create a sub-node."""
		root=self._root()

		if isinstance(name,str):
			name = name.split('/')
		if len(_name) == 1:
			_name = _name[0].split('/')
		for n in chain(_name,name):
			if create and n not in self:
				try:
					res = await root._conn.set(self.path+'/'+n, prevExist=False, dir=True, value=None)
				except etcd.EtcdAlreadyExist: # pragma: no cover ## timing
					res = await root._conn.get(self.path+'/'+n)
				await root.wait(res.modifiedIndex)
			self = self[n]
			if isinstance(self,mtAwaiter):
				self = await self.__await__()
		return self

	def tagged(self,tag):
		"""Generator to find all sub-nodes with a tag"""
		assert tag[0] == ':'
		for k,v in self.items():
			if k == tag:
				yield v
			elif k[0] == ':':
				pass
			elif isinstance(v,mtDir):
				yield from v.tagged(tag)

	def __contains__(self,key):
		return key in self._data

	def __setitem__(self, key,val):
		"""\
			Update a node.
			This just tells etcd to update the value.
			The actual update happens when the watcher sees it.

			The value may be a dictionary, in which case the code
			recursively descends into it.

			@key=None is not supported.
			"""
		if self._frozen: # pragma: no cover
			raise FrozenError(self.path)
		try:
			res = self._data[key]
		except KeyError:
			# new node. Send a "set" command for the data item.
			# (or items, if it's a dict)
			root = self._root()
			def t_set(path,keypath,key,val):
				keypath += (key,)
				path += '/'+key
				if isinstance(val,dict):
					if val:
						for k,v in val.items():
							t_set(path,keypath,k,v)
					else:
						self._task(root._conn.set,path, None, prevExist=False, dir=True)
				else:
					t = root._types.lookup(keypath, dir=False)
					if t is None:
						if self._final is not None:
							raise UnknownNodeError(key)
						t = mtValue
					self._task(root._conn.set,path, t._dump(val), prevExist=False)
			t_set(self.path,self._keypath,key, val)
		else:
			assert isinstance(res,mtValue)
			res.value = val

	async def set(self, key,value, sync=True, **kw):
		"""\
			Update a node. This is the coroutine version of assignment.
			Returns the operation's modification index.

			If @key is None, this code will do an etcd "append" operation
			and the return value will be a key,modIndex tuple.
			"""
		root = self._root()
		if self._frozen: # pragma: no cover
			raise FrozenError(self.path)
		try:
			if key is None:
				raise KeyError
			else:
				res = self._data[key]
		except KeyError:
			# new node. Send a "set" command for the data item.
			# (or items if it's a dict)
			async def t_set(path,keypath,key,value):
				path += '/'+key
				keypath += (key,)
				mod = None
				if isinstance(value,dict):
					if value:
						for k,v in value.items():
							r = await t_set(path,keypath,k,v)
							if r is not None:
								mod = r
					else: # empty dict
						r = await root._conn.set(path, None, dir=True, **kw)
						mod = r.modifiedIndex
				else:
					t = root._types.lookup(keypath, dir=False)
					if t is None:
						if self._final is not None:
							raise UnknownNodeError(key)
						t = mtValue
					r = await root._conn.set(path, t._dump(value), prevExist=False, **kw)
					mod = r.modifiedIndex
				return mod
			if key is None:
				if isinstance(value,dict):
					r = await root._conn.set(self.path, None, append=True, dir=True)
					res = r.key.rsplit('/',1)[1]
					mod = await t_set(self.path,self._keypath,res, value)
					if mod is None:
						mod = r.modifiedIndex # pragma: no cover
				else:
					t = root._types.lookup(self._keypath+('0',), dir=False)
					if t is None:
						t = mtValue
					r = await root._conn.set(self.path, t._dump(value), append=True, **kw)
					res = r.key.rsplit('/',1)[1]
					mod = r.modifiedIndex
				res = res,mod
			else:
				res = mod = await t_set(self.path,self._keypath,key, value)
		else:
			assert isinstance(res,mtValue)
			res = mod = await res.set(value, **kw)
		if sync and mod and root:
			await root.wait(mod)
		return res

	def __delitem__(self, key=_NOTGIVEN):
		"""\
			Delete a node.
			This just tells etcd to delete the key.
			The actual deletion happens when the watcher sees it.

			This will fail if the directory is not empty.
			"""
		if self._frozen: # pragma: no cover
			raise FrozenError(self.path)
		if key is not _NOTGIVEN:
			res = self._data[key]
			res.__delitem__()
			return
		self._task(self._root()._conn.delete,self.path,dir=True, index=self._seq)

	async def update(self, d1={}, _sync=True, **d2):
		mod = None
		for k,v in chain(d1.items(),d2.items()):
			mod = await self.set(k,v, sync=False)
		if _sync and mod:
			root = self._root()
			if root:
				await root.wait(mod)

	async def delete(self, key=_NOTGIVEN, sync=True, recursive=None, **kw):
		"""\
			Delete a node.
			Recursive=True: drop it sequentially
			Recursive=False: don't do anything if I have sub-nodes
			Recursive=None(default): let etcd handle it
			"""
		root = self._root()
		if self._frozen: # pragma: no cover
			raise FrozenError(self.path)
		if key is not _NOTGIVEN:
			res = self._data[key]
			await res.delete(sync=sync,recursive=recursive, **kw)
			return
		if recursive:
			for v in list(self._data.values()):
				await v.delete(sync=sync,recursive=recursive)
		r = await root._conn.delete(self.path, dir=True, recursive=(recursive is None))
		r = r.modifiedIndex
		if sync and root:
			await root.wait(r)
		return r

	def _ext_delete(self):
		"""We vanished. Oh well."""
		for d in list(self._data.values()):
			d._ext_delete()
		super()._ext_delete()

	# used for testing
	def __eq__(self, other):
		## don't check that, non-leaves might be OK
		#if type(self) != type(other):
		#	return False
		if not hasattr(other,'_data'):
			return False # pragma: no cover
		return self._data == other._data

	def _ext_lookup(self, name, dir=None, value=None, **kw):
		"""\
			Do a node lookup.

			@name: my name, as seen by my parent.
			@cls: the class the object is supposed to have.
			@dir: The node type.

			If @cls or @dir is passed in, the node is created if it doesn't
			already exist, else an AttributeError is raised.

			Returns: the child node plus a "created" flag.
			"""
		assert name != ""
		obj = self._data.get(name,None)
		if obj is not None:
			if dir is not None:
				assert isinstance(obj,mtDir if dir else mtValue)
			return obj

		if self._frozen: # pragma: no cover
			raise FrozenError(self.path+'/'+name)
		if dir is None: # pragma: no cover
			return None
		cls = self._root()._types.lookup(self._keypath+(name,), dir=dir)
		if cls is None:
			if self._final:
				return None
			cls = mtDir if dir else mtValue
		else:
			assert issubclass(cls,mtDir if dir else mtValue)

		try:
			value = cls._load(value)
		except Exception as e: # pragma: no cover
			logger.error("Could not load '%s' as %s at %s/%s", value, str(cls),self.path,name)
			value = repr(value)
			cls = mtDir if dir else mtValue
		obj = cls(parent=self,name=name, value=value, **kw)
		self._data[name] = obj
		return obj

	def _ext_update(self, value=None, **kw):
		"""processed for doing a TTL update"""
		assert value is None
		super(mtDir,self)._ext_update(**kw)

	def _ext_del_node(self, child):
		"""Called by the child to tell us that it vanished"""
		node = self._data.pop(child.name)
		node._deleted()

	def _freeze(self):
		super(mtDir,self)._freeze()
		for v in self._data.values():
			v._freeze()

class mtRoot(mtDir):
	"""\
		Root node for a (watched) config tree.

		@conn: the connection this is attached to
		@watcher: the watcher that's talking to me
		@types: type lookup
		@env: optional pointer to the caller's global environment
		"""
	_parent = None
	name = ''
	_path = ''
	_types = None

	def __init__(self,conn,watcher,types=None, env=None, **kw):
		self._conn = conn
		self._watcher = watcher
		self.path = watcher.key if watcher else ''
		self._keypath = ()
		self._tasks = []
		self._loop = conn._loop
		if types is None:
			from .etcd import EtcTypes
			types = EtcTypes()
		self._types = types
		self._env = env
		super(mtRoot,self).__init__(**kw)

	@property
	def parent(self):
		return None

	@property
	def stopped(self):
		return self._watcher.stopped

	async def close(self):
		w,self._watcher = self._watcher,None
		if w is not None:
			await w.close()

	async def wait(self, mod=None, timeout=None):
		if self._tasks:
			tasks,self._tasks = self._tasks,[]
			done,tasks = await asyncio.wait(tasks, timeout=timeout, loop=self._loop)
			self._tasks.extend(tasks)
			while done:
				t = done.pop()
				try:
					r = t.result()
				except Exception as exc: # pragma: no cover
					self._tasks.extend(done)
					raise
				r = getattr(r,'modifiedIndex',None)
				if mod is None or (r is not None and mod < r):
					mod = r # pragma: no cover # because we pop off the end
		if self._watcher is not None:
			await self._watcher.sync(mod)

	def __repr__(self): # pragma: no cover
		try:
			return "<{} @{}>".format(self.__class__.__name__,self._conn.root)
		except Exception as e:
			logger.exception(e)
			res = super(mtBase,self).__repr__()
			return res[:-1]+" ?? "+res[-1]

	def __del__(self):
		self._kill()
	def _kill(self):
		w,self._watcher = self._watcher,None
		if w is not None:
			w._kill() # pragma: no cover # as the tests call close()

	def delete(self, key=_NOTGIVEN, **kw):
		if key is _NOTGIVEN:
			raise RuntimeError("You can't delete the root") # pragma: no cover
		return super().delete(key=key, **kw)

