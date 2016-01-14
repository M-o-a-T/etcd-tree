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

import asyncio
import pytest
import etcd
from etcd_tree.node import EtcDir

from .util import cfg,client

def test_basic_etcd(client):
    pass

def test_invalid_etcd():
    kw = cfg['config']['etcd'].copy()
    r = kw.pop('root','/etcd_tree/test')
    from etcd_tree.etcd import EtcClient
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
async def test_get_set(client):
    """Basic get/set stuff"""
    d=dict
    assert (await client._d()) == d()
    await client.set("/foo","dud")
    await client.set("/what/so","ever")
    assert (await client._d()) == d(foo="dud",what=d(so="ever"))
    assert (await client._d("/what/so")) == "ever"
    assert (clean_dump((await client._d("/what/so",dump=True)))) == \
        d(_=d(action='get', key='/test/etcd_tree/what/so', value='ever'))
    du = clean_dump((await client._d(dump=True)))
    assert du == d(
        _=d(action='get', dir=True, key='/test/etcd_tree'),
        foo=d(key='/test/etcd_tree/foo', value='dud'),
        what= d(_=d(dir=True, key='/test/etcd_tree/what'),
          so=d(key='/test/etcd_tree/what/so', value='ever')))

    v = await client.read("/foo")
    assert v.value == "dud"

    # don't replace things which somebody else changed behind your back
    with pytest.raises(etcd.EtcdCompareFailed):
        await client.set("/foo","bar",prev="guzk")
    with pytest.raises(etcd.EtcdCompareFailed):
        await client.set("/foo","bar",index=v.etcd_index+100)
    x=await client.set("/foo","bari",prev="dud")
    assert (await client._d()) == d(foo="bari",what=d(so="ever"))
    await client.set("/foo","bar",index=x.modifiedIndex)
    assert (await client._d()) == d(foo="bar",what=d(so="ever"))
    assert (await client.get("/foo")).value == "bar"
    v=await client.read("/foo")
    assert v.value == "bar"
    # Verify that the key has in fact been replaced, not blindly overwritten
    assert v.createdIndex < v.etcd_index
    # random entry creation
    r = await client.set("/",value="baz",append=True)
    assert r.key.endswith('000'+str(r.modifiedIndex))
test_get_set._is_oroutine = True

@pytest.mark.run_loop
async def test_feeding(client):
    """Feed data into etcd and check that they arrive."""
    # basic stuff
    d=dict
    d1=d(one="eins",two=d(zwei="drei",vier="fünf"),x="y")
    await client._f(d1)
    assert (await client.get("/one")).value == "eins"
    assert (await client.get("/two/vier")).value == "fünf"

    # Now replace an entry with a tree and vice versa
    d2=d(two="drei",one=d(a="b"),x="y")
    await client._f(d2,delete=True)
    assert (await client._d()) == d(two="drei",one=d(a="b"),x="y")

    # An entry that is in the way should get deleted
    await client._f("nix",subtree="/two/zero")
    assert (await client._d()) == d(two=d(zero="nix"),one=d(a="b"),x="y")

