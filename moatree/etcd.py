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
This is the etcd interface.
"""

from etcd.client import Client

class _NOTGIVEN: pass

class EtcClient(object):
	def __init__(self, root="", **args):
		assert (root == '' or root[0] == '/')
		self.root = root
		self.args = args
		self.client = Client(**args)

	def __del__(self):
		self.client.close()

	def _extkey(self, key):
		key = str(key)
		assert (key == '' or key[0] == '/')
		return self.root+key

	def get(self, key, **kw):
		return self.client.get(self._extkey(key), **kw)

	def read(self, key, **kw):
		return self.client.read(self._extkey(key), **kw)
	
	def set(self, key, value, prev=_NOTGIVEN, index=None, **kw):
		"""\
			Either create or update a value.

			@key: the object path.

			@ttl: time-to-live in seconds.

			@append: generate a new guaranteed-unique and sequential entry.

			"""
		if prev is _NOTGIVEN and index is None:
			kw['prevExists'] = True
		elif not kw.get('append',False):
			kw['prevExists'] = False
			if index is not None:
				kw['prevIndex'] = index
			if prev is not _NOTGIVEN:
				kw['prevValue'] = prev

		return self.client.write(self._extkey(key), value=value, **kw)

	def watch(self, key, cls, immediate=True):
		"""\
			Generate an object tree, populate it, and update it.

			If @immediate is set, run a recursive query and grab everything now.
			Otherwise fill the tree in the background.
			"""
		root = cls()
		return root
		

