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
import time
import asyncio
from etctree.node import mtRoot,mtDir,mtValue,mtInteger,mtString, UnknownNodeError,FrozenError

from .util import cfg,client

@pytest.mark.asyncio
def test_basic_watch(client):
    """Watches which don't actually watch"""
    # object type registration
    class rRoot(mtRoot):
        pass
    @rRoot._register("two")
    class rTwo(mtDir):
        pass
    # reg funcion shall return the right thing
    i = rTwo._register("vier",mtInteger)
    assert i is mtInteger
    i = rTwo._register("vierixx")(mtInteger)
    assert i is mtInteger

    d=dict
    t = client
    d1=d(one="eins",two=d(zwei=d(und="drei"),vier="5"),x="y")
    yield from t._f(d1)
    # basic access, each directory separately
    class xRoot(mtRoot):
        pass
    t.register("/two")(xRoot)
    w = yield from t.tree("/two", immediate=False, static=True)
    assert isinstance(w,xRoot)
    assert w['zwei']['und'] == "drei"
    assert w['vier'] == "5"
    with pytest.raises(KeyError):
        w['x']
    # basic access, read it all at once
    w2 = yield from t.tree("/two",mtRoot, immediate=True, static=True)
    assert w2['zwei']['und'] == "drei"
    assert w['vier'] == "5"
    assert w == w2

    yield from t._f(d(two=d(sechs="sieben")))
    # use typed subtrees
    t.register("/",rRoot)
    w3 = yield from t.tree("/", static=True)
    assert w3['two']['vier'] == 5
    assert w3['two']['sechs'] == "sieben"
    assert not w3['two'] == w2
    # which are different, but not because of the tree types
    w4 = yield from t.tree("/",mtRoot, static=True)
    assert not w3 == w4
    assert w3['x'] == w4['x']
    assert type(w3) is not type(w4)

    # check basic node iterators
    res=set()
    for v in w3['two']['zwei'].values():
        assert not isinstance(v,mtValue)
        res.add(v)
    assert res == {"drei"}

    res=set()
    for k in w3['two'].keys():
        res.add(k)
    assert res == {"zwei","vier","sechs"}

    res=set()
    for k,v in w3['two'].items():
        res.add(k)
        assert v == w3['two'][k]
    assert res == {"zwei","vier","sechs"}

@pytest.mark.asyncio
def test_update_watch_direct(client):
    """Testing auto-update, both ways"""
    d=dict
    t = client
    w = yield from t.tree("/two",mtRoot, immediate=False, static=False)
    d2=d(two=d(zwei=d(und="mehr"),vier=d(auch="xxx",oder="fünfe")))
    mod = yield from t._f(d2,delete=True)
    yield from w._wait(mod=mod)

    w['vier']
    w['vier']['auch']
    yield from w['vier'].delete('auch')
    with pytest.raises(KeyError):
        w['vier']['auch']
    with pytest.raises(KeyError):
        w['zwei']['zehn']
    # Now test that adding a node does the right thing
    yield from w['vier'].set('auch',"ja")
    yield from w['zwei'].set('zehn',d(zwanzig=30,vierzig=d(fuenfzig=60)))
    yield from w['zwei'].set('und', "weniger")

    assert w['zwei']['und'] == "weniger"
    assert w['zwei']['zehn']['zwanzig'] == "30"
    assert w['zwei']['zehn']['vierzig']['fuenfzig'] == "60"
    assert w['vier']['auch'] == "ja"

    
    with pytest.raises(NotImplementedError): # TODO
        w.delete('vier')

    w._get('zwei')._freeze()
    with pytest.raises(FrozenError): # TODO
        w['zwei']['ach'] = 'nee'


@pytest.mark.asyncio
def test_update_watch(client):
    """Testing auto-update, both ways"""
    d=dict
    t = client
    d1=d(one="eins",two=d(zwei=d(und="drei"),vier="fünf",sechs="sieben",acht=d(neun="zehn")))
    yield from t._f(d1)
    w = yield from t.tree("/two",mtRoot, immediate=False, static=False)
    assert w['sechs'] =="sieben"
    assert w['acht']['neun'] =="zehn"
    d2=d(two=d(zwei=d(und="mehr"),vier=d(auch="xxx",oder="fünfe")))
    mod = yield from t._f(d2,delete=True)
    yield from w._wait(mod=mod)
    assert w['zwei']['und']=="mehr"
    assert w['vier']['oder']=="fünfe"
    assert w['vier']['auch']=="xxx"
    assert "oder" in w['vier']
    assert "oderr" not in w['vier']

    # Directly insert "deep" entries
    yield from t.client.write(client._extkey('/two/three/four/five/six/seven'),value=None,dir=True)
    mod = (yield from t.client.write(client._extkey('/two/three/four/fiver'),"what")).modifiedIndex
    yield from w._wait(mod)
    # and check that they're here
    assert w['three']['four']['fiver'] == "what"
    assert isinstance(w['three']['four']['five']['six']['seven'], mtDir)
    # The ones deleted by _f(…,delete=True) should not be
    with pytest.raises(KeyError):
        w['sechs']
    with pytest.raises(KeyError):
        w['acht']
    # deleting a whole subtree is not yet implemented
    with pytest.raises(NotImplementedError): # TODO
        del w['vier']
    del w['vier']['oder']
    yield from w._wait()
    w['vier']
    w['vier']['auch']
    with pytest.raises(KeyError):
        w['vier']['oder']
    del w['vier']['auch']
    yield from w._wait()
    with pytest.raises(KeyError):
        w['vier']['auch']
    # Now test that adding a node does the right thing
    w['vier']['auch'] = "ja"
    w['zwei']['zehn'] = d(zwanzig=30,vierzig=d(fuenfzig=60))
    w['zwei']['und'] = "weniger"
    logger.debug("WAIT FOR ME")
    yield from w['zwei']._wait()

    from etctree import client as rclient
    from .util import cfgpath
    tt = yield from rclient(cfgpath)
    w1 = yield from tt.tree("/two",mtRoot, immediate=True)
    assert w is not w1
    assert w == w1
    wx = yield from tt.tree("/two",mtRoot, immediate=True)
    assert wx is w1
    w2 = yield from t.tree("/two",mtRoot, static=True)
    assert w1 is not w2
    assert w1['zwei']['und'] == "weniger"
    assert w1['zwei'].get('und') == "weniger"
    assert w1['zwei']._get('und').value == "weniger"
    assert w1['zwei'].get('und','nix') == "weniger"
    assert w1['zwei']._get('und','nix').value == "weniger"
    assert w1['zwei'].get('huhuhu','nixi') == "nixi"
    assert w1['zwei']._get('huhuhu','nixo') == "nixo"
    with pytest.raises(KeyError):
        w1['zwei'].get('huhuhu')
    with pytest.raises(KeyError):
        w1['zwei']._get('huhuhu')
    assert w2['zwei']['und'] == "weniger"
    assert w1['zwei']['zehn']['zwanzig'] == "30"
    assert w2['zwei']['zehn']['zwanzig'] == "30"
    assert w1['vier']['auch'] == "ja"
    assert w2['vier']['auch'] == "ja"
    yield from w1._wait()

    # _final=false means I can't add new untyped nodes
    mtDir._register("new_a",mtString)
    mtDir._register("new_b",mtString)
    w1._get('vier')._final = False
    mod = yield from t._f(d2,delete=True)
    yield from w1._wait()
    w1['vier']['auch'] = "nein"
    #assert w1.vier.auch == "ja" ## should be, but too dependent on timing
    with pytest.raises(UnknownNodeError):
        w1['vier']['nix'] = "da"
    with pytest.raises(UnknownNodeError):
        yield from w1['vier'].set('nix', "da")
    w1['vier']['new_a'] = "e_a"
    yield from w1._wait()
    assert w1['vier']['auch'] == "nein"
    with pytest.raises(KeyError):
        assert w1['vier']['dud']
    assert w1['vier']['new_a'] == "e_a"

    d1=d(two=d(vier=d(a="b",c="d")))
    mod = yield from t._f(d1)
    yield from w1._wait()
    assert w1['vier']['a'] == "b"
    with pytest.raises(KeyError):
        w1['vier']['new_b']

    # _final=true means external additions don't come through either
    w1._get('vier')._final = True
    d1=d(two=d(vier=d(c="x",d="y",new_b="z")))
    mod = yield from t._f(d1)
    yield from w1._wait()
    assert w1['vier']['c'] == "x"
    with pytest.raises(KeyError):
        w1['vier']['d']
    with pytest.raises(UnknownNodeError):
        w1['vier']['nixy'] = "daz"
    with pytest.raises(UnknownNodeError):
        yield from w1['vier'].set('nixy', "daz")
    assert w1['vier']['new_b'] == "z"

@pytest.mark.asyncio
def test_update_ttl(client):
    d=dict
    t = client

    mod = yield from t._f(d(nice=d(timeout=d(of="data"),nodes="too")))
    w = yield from t.tree("/nice")
    assert w['timeout']['of'] == "data"
    assert w['timeout']._ttl is None
    assert w['nodes'] == "too"
    assert w._get('nodes')._ttl is None
    logger.warning("_SET_TTL")
    w._get('timeout')._ttl = 1
    w._get('nodes')._ttl = 1
    logger.warning("_SYNC_TTL")
    yield from w._wait()
    logger.warning("_GET_TTL")
    assert w._get('timeout')._ttl is not None
    assert w['nodes'] == "too"
    assert w._get('nodes')._ttl is not None
    del w._get('nodes')._ttl
    yield from asyncio.sleep(2)
    with pytest.raises(KeyError):
        w['timeout']
    assert w['nodes'] == "too"
    assert w._get('nodes')._ttl is None

@pytest.mark.asyncio
def test_create(client):
    t = client
    with pytest.raises(etcd.EtcdKeyNotFound):
        yield from t.tree("/not/here",mtRoot, immediate=True, static=True, create=False)
    w1 = yield from t.tree("/not/here",mtRoot, immediate=True, static=True, create=True)
    w2 = yield from t.tree("/not/here",mtRoot, immediate=True, static=True, create=False)

    w2 = yield from t.tree("/not/there",mtRoot, immediate=True, static=True)
    w3 = yield from t.tree("/not/there",mtRoot, immediate=True, static=True, create=False)
    w4 = yield from t.tree("/not/there",mtRoot, immediate=True, static=True)
    with pytest.raises(etcd.EtcdAlreadyExist):
        yield from t.tree("/not/there",mtRoot, immediate=True, static=True, create=True)

