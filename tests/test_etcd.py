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

import pytest
import etcd
from etctree.node import mtDir

from .util import cfg,client

def test_basic_etcd(client):
    pass

def test_invalid_etcd():
    kw = cfg['config']['etcd'].copy()
    r = kw.pop('root','/etctree/test')
    from etctree.etcd import EtcClient
    with pytest.raises(AssertionError):
        EtcClient(root="nix", **kw)

def clean_dump(d):
    d.pop('modifiedIndex',None)
    d.pop('createdIndex',None)
    d.pop('etcd_index',None)
    d.pop('raft_index',None)
    for v in d.values():
        if isinstance(v,dict):
            clean_dump(v)
    return d

@pytest.mark.run_loop
def test_get_set(client):
    """Basic get/set stuff"""
    d=dict
    assert (yield from client._d()) == d()
    yield from client.set("/foo","dud")
    yield from client.set("/what/so","ever")
    assert (yield from client._d()) == d(foo="dud",what=d(so="ever"))
    assert (yield from client._d("/what/so")) == "ever"
    assert (clean_dump((yield from client._d("/what/so",dump=True)))) == \
        d(_=d(action='get', key='/test/etctree/what/so', value='ever'))
    du = clean_dump((yield from client._d(dump=True)))
    assert du == d(
        _=d(action='get', dir=True, key='/test/etctree'),
        foo=d(key='/test/etctree/foo', value='dud'),
        what= d(_=d(dir=True, key='/test/etctree/what'),
          so=d(key='/test/etctree/what/so', value='ever')))

    v = yield from client.read("/foo")
    assert v.value == "dud"

    # don't replace things which somebody else changed behind your back
    with pytest.raises(etcd.EtcdCompareFailed):
        yield from client.set("/foo","bar",prev="guzk")
    with pytest.raises(etcd.EtcdCompareFailed):
        yield from client.set("/foo","bar",index=v.etcd_index+100)
    x=yield from client.set("/foo","bari",prev="dud")
    assert (yield from client._d()) == d(foo="bari",what=d(so="ever"))
    yield from client.set("/foo","bar",index=x.modifiedIndex)
    assert (yield from client._d()) == d(foo="bar",what=d(so="ever"))
    assert (yield from client.get("/foo")).value == "bar"
    v=yield from client.read("/foo")
    assert v.value == "bar"
    # Verify that the key has in fact been replaced, not blindly overwritten
    assert v.createdIndex < v.etcd_index
    # random entry creation
    r = yield from client.set("/",value="baz",append=True)
    assert r.key.endswith('000'+str(r.modifiedIndex))

@pytest.mark.run_loop
def test_feeding(client):
    """Feed data into etcd and check that they arrive."""
    # basic stuff
    d=dict
    d1=d(one="eins",two=d(zwei="drei",vier="fünf"),x="y")
    yield from client._f(d1)
    assert (yield from client.get("/one")).value == "eins"
    assert (yield from client.get("/two/vier")).value == "fünf"

    # Now replace an entry with a tree and vice versa
    d2=d(two="drei",one=d(a="b"),x="y")
    yield from client._f(d2,delete=True)
    assert (yield from client._d()) == d(two="drei",one=d(a="b"),x="y")

    # An entry that is in the way should get deleted
    yield from client._f("nix",subtree="/two/zero")
    assert (yield from client._d()) == d(two=d(zero="nix"),one=d(a="b"),x="y")

