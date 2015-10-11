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

"""\
This declares nodes for the basic MoaTree structure.
"""

import weakref

class _NOTGIVEN:
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
	_root_cache = None

	def __init__(self, parent, name, seq=None):
		self._parent = weakref.ref(parent)
		self._name = name
		if name is None:
			# This is a root node, the parent is the actual watcher
			self._root_cache = (self._parent,'')
		self._seq = seq
	
	def _set_up(self):
		"""Override this method to get notified when initial subtree set-up is completed"""
		pass
	def _updated(self):
		"""Override this method to get notified when my value changes"""
		pass
	def _deleted(self):
		"""Override this method to get notified when this node gets dropped"""
		pass

	@property
	def _root(self):
		"""Return 'my' root"""
		if self._root_cache is None:
			r,p = self._parent()._root
			p += '/'+self._name
			self._root_cache = (r,p)
		return self._root_cache[0]

	@property
	def _path(self):
		"""Return the path from my root node to me"""
		if self._root_cache is None:
			r,p = self._parent()._root
			p += '/'+self._name
			self._root_cache = (r,p)
		return self._root_cache[1]

	def _ext_delete(self, seq=None):
		self._parent()._ext_del_node(self)
		
class mtValue(mtBase):
	"""A value node, i.e. the leaves of the etcd tree."""
	type = str

	_seq = None
	def __init__(self, value, **kw):
		super().__init__(**kw)
		self._value = value
	
	# used for testing
	def __eq__(self, other):
		if type(self) != type(other):
			return False
		return self.value == other.value

	@staticmethod
	def _load(value):
		return self.type(value)
	@staticmethod
	def _dump(value):
		return str(value)
	
	def _get_value(self):
		return self._value
	def _set_value(self,value):
		self._root.conn.write(self._path,self._dump(_value), index=self._seq)
	def _del_value(self):
		self._root.conn.delete(self._path,self._dump(_value), index=self._seq)
	value = property(_get_value, _set_value, _del_value)

	def _ext_update(self, value, seq=None):
		"""\
			An updated value arrives.
			"""
		self._value = self._load(value)
		self._seq = seq
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

		If @_final is set, un-registered entries will be ignored.
		If true, an exception will be raised.
		"""
	_types = None
	_final = None

	def __init__(self, **kw):
		super().__init__(**kw)
		self._data = {}

	def __iter__(self):
		return self._data.items()

	def __getattr__(self, key):
		res = self._data[key]
		if isinstance(res,mtValue):
			return res.value
		return res

	@classmethod
	def _register(cls, name, sub):
		"""Teach this node that a sub-node named @name is to be of type @sub"""
		cls._types[name] = sub

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
			# new node
			t = self.types.get(key, mtDir if not isinstance(t,dict) else mtValue)
			self._root.conn.write(self._path+'/'+key, t._dump(_value), prevExist=False)
		else:
			if isinstance(res,mtValue):
				res.value = val
		raise NotImplementedError

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
		if type(self) != type(other):
			return False
		return self._data == other._data

	def _ext_lookup(self, name, cls=None, dir=None, **kw):
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
			if cls is not None:
				assert isinstance(obj,cls)
			if dir is not None:
				assert isinstance(obj,mtDir if dir else mtValue)
			return obj

		if cls is None:
			if dir is None:
				raise AttributeError(name)
			cls = self._types.get(name, None)
			if cls is None:
				if self._final is not None:
					if self._final:
						raise UnknownNodeError(self._path,name)
					return
				cls = mtDir if dir else mtValue

		obj = cls(parent=self,name=name, **kw)
		self._data[name] = obj
		return obj
	
	def _ext_del_node(self, child):
		"""Called by the child to tell us that it vanished"""
		node = self._data.pop(child._name)
		node._deleted()

	def _all_attrs(self):
		"""Called by etcd after all non-directory nodes have been filled"""
		pass

	def _all_nodes(self):
		"""Called by etcd after all directory nodes have been filled also"""
		pass

	# for easier access to variably-named nodes
	__getitem__ = __getattr__
	__setitem__ = __setattr__
	__delitem__ = __delattr__
