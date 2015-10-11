# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division, unicode_literals
##
##  This file is part of MoaTree
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

import pytest
import etcd
from dabroker.util import attrdict

from .util import cfg

@pytest.fixture
def client():
    """An interface to a clean etcd subtree"""
    kw = cfg.config.etcd.copy()
    r = kw.pop('root','/moatree/test')

    from moatree.etcd import EtcClient
    c = EtcClient(root=r, **kw)
    try:
        c.client.delete(c.root, recursive=True)
    except etcd.EtcdKeyNotFound:
        pass
    c.client.write(c.root, dir=True, value=None)
    def dumper(client):
        from moatree.test import from_etcd
        return from_etcd(client.client,client.root)
    def feeder(client,data, delete=False,subtree=""):
        from moatree.test import to_etcd
        return to_etcd(client.client,client.root+subtree,data, delete=delete)
    type(c)._d = dumper
    type(c)._f = feeder

    return c
    
def test_basic_etcd(client):
    pass

def test_invalid_etcd():
    kw = cfg.config.etcd.copy()
    r = kw.pop('root','/moatree/test')
    from moatree.etcd import EtcClient
    with pytest.raises(AssertionError):
        EtcClient(root="nix", **kw)
    
def test_get_set(client):
    """Basic get/set stuff"""
    d=attrdict
    assert client._d() == d()
    client.set("/foo","dud")
    client.set("/what","ever")
    assert client._d() == d(foo="dud",what="ever")
    v=client.read("/foo")
    assert v.value == "dud"

    # don't replace things which somebody else changed behind your back
    with pytest.raises(etcd.EtcdCompareFailed):
        client.set("/foo","bar",prev="guzk")
    with pytest.raises(etcd.EtcdCompareFailed):
        client.set("/foo","bar",index=v.etcd_index+100)
    x=client.set("/foo","bari",prev="dud")
    assert client._d() == d(foo="bari",what="ever")
    client.set("/foo","bar",index=x.modifiedIndex)
    assert client._d() == d(foo="bar",what="ever")
    assert client.get("/foo").value == "bar"
    v=client.read("/foo")
    assert v.value == "bar"
    # Verify that the key has in fact been replaced, not blindly overwritten
    assert v.createdIndex < v.etcd_index
    # random entry creation
    r = client.set("/",value="baz",append=True)
    assert r.key.endswith('000'+str(r.modifiedIndex))

def test_feeding(client):
    """Feed data into etcd and check that they arrive."""
    # basic stuff
    d=attrdict
    d1=d(one="eins",two=d(zwei="drei",vier="fünf"),x="y")
    client._f(d1)
    assert client.get("/one").value == "eins"
    assert client.get("/two/vier").value == "fünf"

    # Now replace an entry with a tree and vice versa
    d2=d(two="drei",one=d(a="b"),x="y")
    client._f(d2,delete=True)
    assert client._d() == d(two="drei",one=d(a="b"),x="y")

    # An entry that is in the way should get deleted
    client._f("nix",subtree="/two/zero")
    assert client._d() == d(two=d(zero="nix"),one=d(a="b"),x="y")




