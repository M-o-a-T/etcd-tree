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

class _NOTGIVEN:
	pass

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

class mtBase(object):
	"""\
		Abstract base class for an etcd node.

		@parent: The node's parent
		@name: the node's name (without path)
		@seq: modification seqno from etcd, to reject old updates

		All mthods have a leading underscore, which is necessary because
		non-underscored names are potential etcd node names.
		"""
	_monitor = None
	_frozen = False

	def __init__(self, parent=None, name=None, seq=None, cseq=None, ttl=None):
		if name:
			self._parent = weakref.ref(parent)
			self._root = parent._root
			self._name = name
			self._path = parent._path+'/'+name
			self._keypath = parent._keypath+(name,)
		else:
			# This is a root node
			self._root = weakref.ref(self)
		self._seq = seq
		self._cseq = cseq
		self._xttl = ttl
		self._timestamp = time.time()
	
	def _task(self,p,*a,**k):
		f = asyncio.async(p(*a,**k))
		f.args = (self,p,a,k)
		self._root()._tasks.append(f)

	@asyncio.coroutine
	def _wait(self,mod=None,timeout=None):
		yield from self._root()._wait(mod, timeout=timeout)
	_wait._is_coroutine = True

	def __repr__(self): ## pragma: no cover
		try:
			return "<{} @{}>".format(self.__class__.__name__,self._path)
		except Exception as e:
			logger.exception(e)
			res = super(mtBase,self).__repr__()
			return res[:-1]+" ?? "+res[-1]

	def _get_ttl(self):
		if self._xttl is None:
			return None
		return self._xttl - (time.time()-self._timestamp)
	def _set_ttl(self,ttl):
		kw = {}
		if self._is_dir:
			kw['prev'] = None
		else:
			kw['index'] = self._seq
		self._task(self._root()._conn.set,self._path,self._dump(self._value), ttl=ttl, dir=self._is_dir, **kw)
	def _del_ttl(self):
		self._set_ttl('')
	_ttl = property(_get_ttl, _set_ttl, _del_ttl)

	def _freeze(self):
		self._frozen = True

	def _r_updated(self, path=(), seq=None):
		"""call ._updated, then recurse to the parent if that true"""
		if not self._updated(path=path, seq=seq):
			return
		p = self._parent
		if p is None:
			return
		p = p()
		if p is None:
			return # pragma: no cover
		p._r_updated(path=(self._name,)+path, seq=seq)

	def _updated(self, path=(), seq=None):
		"""\
			Override this method to get notified when the value changes
			(or that of a child node).
			Return True if you want the change to be propagated to the
			caller.
			"""
		return False

	def _deleted(self):
		"""Override this method to get notified when this node gets dropped"""
		pass

	def _ext_delete(self, seq=None):
		p = self._parent
		if p is None:
			return
		p = p()
		if p is None:
			return # pragma: no cover
		p._ext_del_node(self)
		
	def _ext_update(self, seq=None, cseq=None, ttl=_NOTGIVEN):
		if seq and self._seq and self._seq >= seq:
			return False # pragma: no cover
		if seq: # pragma: no branch
			self._seq = seq
		if cseq is not None:
			if self._cseq is None:
				self._cseq = cseq
			elif self._cseq != cseq:
				raise RuntimeError("Object re-created but we didn't notice")
		if ttl is not _NOTGIVEN: # pragma: no branch
			self._xttl = ttl
		self._r_updated(seq=seq)
		return True

class mtValue(mtBase):
	"""A value node, i.e. the leaves of the etcd tree."""
	type = str
	_is_dir = False

	_seq = None
	def __init__(self, value=_NOTGIVEN, **kw):
		super().__init__(**kw)
		self._value = value
	
	def _updated(self, path=(), seq=None):
		"""\
			Override to get notified of changes.
			Defaults to returning True for value nodes so that the owner
			gets notified.
			"""
		return True

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
			raise FrozenError(self._path)
		if self._value is _NOTGIVEN: # pragma: no cover
			raise RuntimeError("You did not sync")
		return self._value
	def _set_value(self,value):
		if self._frozen: # pragma: no cover
			raise FrozenError(self._path)
		self._task(self._root()._conn.set,self._path,self._dump(value), index=self._seq)
	def _del_value(self):
		if self._frozen: # pragma: no cover
			raise FrozenError(self._path)
		self._task(self._root()._conn.delete,self._path, index=self._seq)
	value = property(_get_value, _set_value, _del_value)

	@asyncio.coroutine
	def set(self, value, sync=True, ttl=None):
		if self._frozen: # pragma: no cover
			raise FrozenError(self._path)
		root = self._root()
		if root is None:
			return # pragma: no cover
		r = yield from root._conn.set(self._path,self._dump(value), index=self._seq, ttl=ttl)
		if sync:
			yield from root._watcher.sync(r.modifiedIndex)
		return r.modifiedIndex

	@asyncio.coroutine
	def delete(self, sync=True, **kw):
		if self._frozen: # pragma: no cover
			raise FrozenError(self._path)
		root = self._root()
		if root is None:
			return # pragma: no cover
		r = yield from root._conn.delete(self._path, index=self._seq, **kw)
		if sync:
			yield from root._watcher.sync(r.modifiedIndex)
		return r.modifiedIndex

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

class mtDir(mtBase):
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
		for k,v in self._data.items():
			if isinstance(v,mtValue):
				v = v.value
			yield k,v

	@classmethod
	def _load(cls,value):
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
			if isinstance(v,mtValue):
				v = v.value
			yield v
	def items(self):
		return self.__iter__()
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

	def __contains__(self,key):
		return key in self._data

	def __setitem__(self, key,val):
		"""\
			Update a node.
			This just tells etcd to update the value.
			The actual update happens when the watcher sees it.

			The value may be a dictionary, in which case the code
			recursively descends into it.
			"""
		if self._frozen: # pragma: no cover
			raise FrozenError(self._path)
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
					for k,v in val.items():
						t_set(path,keypath,k,v)
				else:
					t = root._types.lookup(keypath, dir=False)
					if t is None:
						if self._final is not None:
							raise UnknownNodeError(key)
						t = mtValue
					self._task(root._conn.set,path, t._dump(val), prevExist=False)
			t_set(self._path,self._keypath,key, val)
		else:
			assert isinstance(res,mtValue)
			res.value = val

	@asyncio.coroutine
	def set(self, key,value, sync=True, **kw):
		"""\
			Update a node. This is the coroutine version of assignment.
			"""
		root = self._root()
		if self._frozen: # pragma: no cover
			raise FrozenError(self._path)
		try:
			res = self._data[key]
		except KeyError:
			# new node. Send a "set" command for the data item.
			# (or items if it's a dict)
			@asyncio.coroutine
			def t_set(path,keypath,key,value):
				path += '/'+key
				keypath += (key,)
				mod = None
				if isinstance(value,dict):
					for k,v in value.items():
						r = yield from t_set(path,keypath,k,v)
						if r is not None:
							mod = r
				else:
					t = root._types.lookup(keypath, dir=False)
					if t is None:
						if self._final is not None:
							raise UnknownNodeError(key)
						t = mtValue
					r = yield from root._conn.set(path, t._dump(value), prevExist=False, **kw)
					mod = r.modifiedIndex
				return mod
			mod = yield from t_set(self._path,self._keypath,key, value)
		else:
			assert isinstance(res,mtValue)
			mod = yield from res.set(value, **kw)
		if sync and mod:
			yield from root._watcher.sync(mod)
		return mod

	def __delitem__(self, key):
		"""\
			Delete a node.
			This just tells etcd to delete the key.
			The actual deletion happens when the watcher sees it.
			"""
		if self._frozen: # pragma: no cover
			raise FrozenError(self._path)
		res = self._data[key]
		if isinstance(res,mtValue):
			del res.value
			return
		raise NotImplementedError

	def delete(self, key, sync=True, **kw):
		"""\
			Delete a node.
			"""
		if self._frozen: # pragma: no cover
			raise FrozenError(self._path)
		res = self._data[key]
		if isinstance(res,mtValue):
			return res.delete(sync=sync, **kw)
		raise NotImplementedError
	delete._is_coroutine = True

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
			raise FrozenError(self._path+'/'+name)
		if dir is None: # pragma: no cover
			raise AttributeError(name)
		cls = self._root()._types.lookup(self._keypath+(name,), dir=dir)
		if cls is None:
			if self._final:
				return None
			cls = mtDir if dir else mtValue
		else:
			assert issubclass(cls,mtDir if dir else mtValue)

		try:
			value = cls._load(value)
		except Exception as e:
			logger.exception("Could not load %s as %s", value, str(cls))
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
		node = self._data.pop(child._name)
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
		"""
	_parent = None
	_name = ''
	_path = ''
	_types = None

	def __init__(self,conn,watcher,types=None, **kw):
		self._conn = conn
		self._watcher = watcher
		self._path = watcher.key if watcher else ''
		self._keypath = ()
		self._tasks = []
		if types is None:
			from .etcd import EtcTypes
			types = EtcTypes()
		self._types = types
		super(mtRoot,self).__init__(**kw)

	@asyncio.coroutine
	def _wait(self, mod=None, timeout=None):
		if self._tasks:
			tasks,self._tasks = self._tasks,[]
			done,tasks = yield from asyncio.wait(tasks, timeout=timeout)
			self._tasks.extend(tasks)
			while done:
				t = done.pop()
				try:
					r = t.result()
				except Exception as exc: # pragma: no cover
					self._tasks.extend(done)
					raise
				if mod is None:
					mod = self._conn.last_mod
				r = getattr(r,'modifiedIndex',None)
				if mod is None or (r is not None and mod < r):
					mod = r # pragma: no cover # because we pop off the end
		yield from self._watcher.sync(mod)

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
			w._kill()
	
