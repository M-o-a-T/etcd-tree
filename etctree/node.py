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

	def __init__(self, parent=None, name=None, seq=None, ttl=None):
		if name:
			self._parent = weakref.ref(parent)
			self._root = parent._root
			self._name = name
			self._path = parent._path+'/'+name
		else:
			# This is a root node
			self._root = weakref.ref(self)
		self._seq = seq
		self._xttl = ttl
		self._timestamp = time.time()
	
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
		self._root()._conn.set(self._path,self._dump(self._value), ttl=ttl, dir=self._is_dir, **kw)
	def _del_ttl(self):
		self._set_ttl('')
	_ttl = property(_get_ttl, _set_ttl, _del_ttl)

	def _freeze(self):
		self._frozen = True

	def _set_up(self):
		"""Override this method to get notified when initial subtree set-up is completed"""
		pass
	def _updated(self):
		"""Override this method to get notified when my value changes"""
		pass
	def _deleted(self):
		"""Override this method to get notified when this node gets dropped"""
		pass

	def _ext_delete(self, seq=None):
		self._parent()._ext_del_node(self)
		
	def _ext_update(self, seq=None, ttl=_NOTGIVEN):
		if seq and self._seq and self._seq >= seq: # pragma: no cover
			return False
		if seq: # pragma: no branch
			self._seq = seq
		if ttl is not _NOTGIVEN: # pragma: no branch
			self._xttl = ttl
		return True

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
			return False
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
		self._root()._conn.set(self._path,self._dump(value), index=self._seq)
	def _del_value(self):
		self._root()._conn.delete(self._path, index=self._seq)
	value = property(_get_value, _set_value, _del_value)

	def _ext_update(self, value, **kw):
		"""\
			An updated value arrives.
			(It may be late.)
			"""
		if not super(mtValue,self)._ext_update(**kw): # pragma: no cover
			return
		self._value = self._load(value)
		self._updated()

mtString = mtValue
class mtInteger(mtValue):
	type = int

class mtTyped(type):
	"""Instantiate a new per-class _types array"""
	def __init__(cls, name, bases, nmspc):
		super(mtTyped, cls).__init__(name, bases, nmspc)
		cls._types = {}

class mtDir(mtBase, metaclass=mtTyped):
	"""\
		A node with other nodes below it.

		If @_final is set, you cannot add unknown entries.
		If true, they also won't be added when the arrive from etcd.

		Map lookup will return a leaf node's mtValue node.
		Access by attribute will return the value directly.
		"""
	_types = None
	_final = None
	_value = None
	_is_dir = True

	def __init__(self, value=None, **kw):
		assert value is None
		super().__init__(**kw)
		self._data = {}

	def __iter__(self):
		return iter(self._data.items())

	@classmethod
	def _load(cls,value):
		assert value is None
		return None
	@classmethod
	def _dump(cls,value): # pragma: no cover
		assert value is None
		return None

	def __getattr__(self, key):
		if key[0] == '_': # pragma: no cover
			return object.__getattribute__(self,key)
		res = self._data[key]
		if isinstance(res,mtValue):
			return res.value
		return res

	def __getitem__(self, key):
		return self._data[key]

	def __contains__(self,key):
		return key in self._data

	@classmethod
	def _register(cls, name, sub=None):
		"""\
			Teach this node that a sub-node named @name is to be of type @sub.
			Can be used as a class decorator:
				class myRoot(mtRoot):
					pass
				@myRoot._register("con")
				class myConn(mtDir):
					pass
				myConn._register("port",mtInteger)
			"""
		def defi(sub):
			cls._types[name] = sub
			return sub
		if sub is None:
			return defi
		else:
			return defi(sub)

	def __setattr__(self, key,val):
		"""\
			Update a node.
			This just tells etcd to update the value.
			The actual update happens when the watcher sees it.
			"""
		if key[0] == '_':
			return object.__setattr__(self, key,val)
		try:
			res = self._data[key]
		except KeyError:
			# new node. Send a "set" command for the data item.
			# (or items if it's a dict)
			def t_set(cls,path,key,val):
				path += '/'+key
				t = cls._types.get(key, None)
				if t is None and self._final is not None:
					raise UnknownNodeError(key)
				if isinstance(val,dict):
					if t is None: # pragma: no branch # missing test due to obviousness
						t = mtDir
					for k,v in val.items():
						t_set(t,path,k,v)
				else:
					if t is None:
						t = mtValue
					self._root()._conn.set(path, t._dump(val), prevExist=False)
			t_set(type(self), self._path,key, val)
		else:
			assert isinstance(res,mtValue)
			res.value = val

	def __delattr__(self, key):
		"""\
			Delete a node.
			This just tells etcd to delete the key.
			The actual deletion happens when the watcher sees it.
			"""
		res = self._data[key]
		if isinstance(res,mtValue):
			del res.value
			return
		raise NotImplementedError

	# used for testing
	def __eq__(self, other):
		## don't check that, non-leaves might be OK
		#if type(self) != type(other):
		#	return False
		return self._data == other._data

	def _ext_lookup(self, name, cls=None, dir=None, value=None, **kw):
		"""\
			Do a node lookup.
			
			@name: my name, as seen by my parent.
			@cls: the class the object is supposed to have.
			@dir: The node type.

			If @cls or @dir is passed in, the node is created if it doesn't
			already exist, else an AttributeError is raised.
			"""
		assert name != ""
		obj = self._data.get(name,None)
		if obj is not None:
			if cls is not None: # pragma: no cover
				assert isinstance(obj,cls)
			if dir is not None:
				assert isinstance(obj,mtDir if dir else mtValue)
			return obj

		if self._frozen: # pragma: no cover
			raise FrozenError(self._path+'/'+name)
		if cls is None:
			if dir is None: # pragma: no cover
				raise AttributeError(name)
			cls = self._types.get(name, None)
			if cls is None:
				if self._final:
					return
				cls = mtDir if dir else mtValue

		obj = cls(parent=self,name=name, value=cls._load(value), **kw)
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

	# for easier access to variably-named nodes
	__setitem__ = __setattr__
	__delitem__ = __delattr__

class mtRoot(mtDir):
	"""\
		Root node for a (watched) config tree.

		@conn: the connection this is attached to
		@watcher: the watcher that's talking to me
		"""
	_parent = None
	_name = ''
	_path = ''

	def __init__(self,conn,watcher, **kw):
		self._conn = conn
		self._watcher = watcher
		self._path = watcher.key if watcher else ''
		super(mtRoot,self).__init__(**kw)

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
	
