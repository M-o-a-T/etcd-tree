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
from etcd_tree.node import mtRoot,mtDir,mtValue,mtInteger,mtFloat,mtString, UnknownNodeError,FrozenError
from etcd_tree.etcd import EtcTypes,WatchStopped

from .util import cfg,client
from unittest.mock import Mock

@pytest.mark.run_loop
@asyncio.coroutine
def test_basic_watch(client,loop):
    """Watches which don't actually watch"""
    # object type registration
    types = EtcTypes()
    twotypes = EtcTypes()
    @twotypes.register()
    class rTwo(mtDir):
        pass
    @twotypes.register("die")
    class rDie(mtValue):
        def has_update(self):
            raise RuntimeError("RIP")
    # reg funcion shall return the right thing
    types.step('two',dest=twotypes)
    assert types.lookup(('two','die'),dir=False) is rDie
    assert types.lookup('two',dir=True,raw=True).lookup('die',dir=False) is rDie
    i = types.register("two","vier", cls=mtInteger)
    assert i is mtInteger
    i = types.register("*/vierixx")(mtInteger)
    assert i is mtInteger
    types['what/ever'] = mtFloat
    types['what/ever'] = rTwo
    assert types.lookup('what','ever', dir=False) is mtFloat
    assert types.lookup('what','ever', dir=True) is rTwo
    assert types['what/ever'] is mtFloat
    with pytest.raises(AssertionError):
        types['/what/ever']
    with pytest.raises(AssertionError):
        types['what/ever/']
    with pytest.raises(AssertionError):
        types['what//ever']
    types['something/else'] = mtInteger
    assert types['two/vier'] is mtInteger
    assert types['something/else'] is mtInteger
    assert types['not/not'] is None

    d=dict
    t = client
    d1=d(one="eins",two=d(zwei=d(und="drei"),vier="5"),x="y")
    yield from t._f(d1)
    # basic access, each directory separately
    class xRoot(mtRoot):
        pass
    types.register(cls=xRoot)
    w = yield from t.tree("/two", immediate=False, static=True, types=types, env="foobar")
    assert isinstance(w,xRoot)
    assert w.env == "foobar"
    assert w['zwei']['und'] == "drei"
    assert w['zwei'].env == "foobar"
    assert w['vier'] == "5"
    with pytest.raises(KeyError):
        w['x']
    # basic access, read it all at once
    w2 = yield from t.tree("/two", immediate=True, static=True, types=types)
    assert w2['zwei']['und'] == "drei"
    assert w['vier'] == "5"
    assert w == w2

    # use typed subtrees
    w4 = yield from t.tree("/", types=types)
    yield from w4.set('two',d(sechs="sieben"))
    w3 = yield from t.tree("/", static=True, types=types)
    assert w3['two']['vier'] == 5
    assert w3['two']['sechs'] == "sieben"
    assert not w3['two'] == w2
    # which are different, but not because of the tree types
    assert not w3 is w4
    assert w3 == w4

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

    # check what happens if an updater dies on us
    yield from w4['two'].set('hello','one')
    yield from w4['two'].set('die',42)
    yield from asyncio.sleep(1.5, loop=loop)
    with pytest.raises(WatchStopped):
        yield from w4['two'].set('hello','two')
    
    yield from w2.close()
    yield from w3.close()
    yield from w4.close()

@pytest.mark.run_loop
@asyncio.coroutine
def test_update_watch_direct(client):
    """Testing auto-update, both ways"""
    d=dict
    t = client
    wr = yield from t.tree("/", sub='two', immediate=False, static=False)
    w = wr['two']
    d2=d(two=d(zwei=d(und="mehr"),drei=d(cold="freezing"),vier=d(auch="xxx",oder="fünfe")))
    mod = yield from t._f(d2,delete=True)
    yield from wr.wait(mod=mod)

    with pytest.raises(KeyError):
        yield from w.subdir('zwei','drei','der', name=":tag")
    tag = yield from w.subdir("zwei/drei",name="der/:tag", create=True)
    tug = yield from w.subdir("zwei/drei/vier",name="das/:tagg", create=True)
    yield from tag.set("hello","kitty")
    yield from tug.set("hello","kittycat")

    w['vier']
    w['vier']['auch']
    yield from w['vier'].delete('auch',prev='xxx')
    with pytest.raises(KeyError):
        w['vier']['auch']
    with pytest.raises(KeyError):
        w['zwei']['zehn']
    # Now test that adding a node does the right thing
    yield from w['vier'].set('auch',"ja1")
    yield from w['zwei'].set('zehn',d(zwanzig=30,vierzig=d(fuenfzig=60)))
    yield from w['zwei'].set('und', "weniger")

    assert w['zwei']['und'] == "weniger"
    assert w['zwei']['zehn']['zwanzig'] == "30"
    assert w['zwei']['zehn']['vierzig']['fuenfzig'] == "60"
    assert w['vier']['auch'] == "ja1"
    assert w['zwei']['drei']['der'][':tag']['hello'] == "kitty"
    n=0
    for k in w.tagged(':tag'):
        n += 1
        assert k['hello']=='kitty'
    assert n==1

    
    m = yield from w.delete('vier')
    yield from wr.wait(m)
    with pytest.raises(KeyError):
        w['vier']

    w._get('drei')._freeze()
    with pytest.raises(FrozenError):
        w['drei']['cold'] = 'nee'

    with pytest.raises(etcd.EtcdDirNotEmpty):
        del w['zwei']
        yield from wr.wait(m)

    m = yield from w.delete('zwei', recursive=True)
    yield from wr.wait(m)
    with pytest.raises(KeyError):
        w['zwei']

    yield from wr.close()

@pytest.mark.run_loop
@asyncio.coroutine
def test_update_watch(client, loop):
    """Testing auto-update, both ways"""
    logger.debug("START update_watch")
    d=dict
    types = EtcTypes()
    t = client
    w = yield from t.tree("/two", immediate=False, static=False)
    d1=d(zwei=d(und="drei",oder={}),vier="fünf",sechs="sieben",acht=d(neun="zehn"))
    yield from w.update(d1)

    m1,m2 = Mock(),Mock()
    f = asyncio.Future(loop=loop)
    def wake(x):
        f.set_result(x)
    i0 = w.add_monitor(wake)
    i1 = w['zwei'].add_monitor(m1)
    i2 = w['zwei']._get('und').add_monitor(m2)

    assert w['sechs'] == "sieben"
    acht = w['acht']
    assert acht['neun'] =="zehn"
    d2=d(two=d(zwei=d(und="mehr"),vier=d(auch="xxy",oder="fünfe")))
    mod = yield from t._f(d2,delete=True)
    yield from w.wait(mod=mod)
    assert w['zwei']['und']=="mehr"
    assert w['vier']['oder']=="fünfe"
    assert w['vier']['auch']=="xxy"
    assert "oder" in w['vier']
    assert "oderr" not in w['vier']

    # Directly insert "deep" entries
    yield from t.client.write(client._extkey('/two/three/four/five/six/seven'),value=None,dir=True)
    mod = (yield from t.client.write(client._extkey('/two/three/four/fiver'),"what")).modifiedIndex
    yield from w.wait(mod)
    # and check that they're here
    assert w['three']['four']['fiver'] == "what"
    assert isinstance(w['three']['four']['five']['six']['seven'], mtDir)

    logger.debug("Waiting for _update 1")
    yield from f
    f = asyncio.Future(loop=loop)
    assert m1.call_count # may be >1
    assert m2.call_count
    mc1 = m1.call_count
    mc2 = m2.call_count
    w['zwei'].remove_monitor(i1)

    # The ones deleted by _f(…,delete=True) should not be
    with pytest.raises(KeyError):
        w['sechs']
    with pytest.raises(KeyError):
        logger.debug("CHECK acht")
        w['acht']
    # deleting a whole subtree is not yet implemented
    with pytest.raises(etcd.EtcdDirNotEmpty):
        del w['vier']
        yield from w.wait()
    del w['vier']['oder']
    yield from w.wait()
    w['vier']
    s = w['vier']._get('auch')._cseq
    with pytest.raises(KeyError):
        w['vier']['oder']
    m = yield from w['vier']._get('auch').delete()
    yield from w.wait(m)
    with pytest.raises(KeyError):
        w['vier']['auch']

    # Now test that adding a node does the right thing
    m = yield from w['vier'].set('auch',"ja2")
    w['zwei']['zehn'] = d(zwanzig=30,vierzig=d(fuenfzig=60))
    w['zwei']['und'] = "weniger"
    logger.debug("WAIT FOR ME")
    yield from w['zwei'].wait(m)
    assert s != w['vier']._get('auch')._cseq

    from etcd_tree import client as rclient
    from .util import cfgpath
    tt = yield from rclient(cfgpath, loop=loop)
    w1 = yield from tt.tree("/two", immediate=True, types=types)
    assert w is not w1
    assert w == w1
    # wx = yield from tt.tree("/two", immediate=True)
    # assert wx is w1 ## no caching
    w2 = yield from t.tree("/two", static=True)
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
    assert w1['vier']['auch'] == "ja2"
    assert w2['vier']['auch'] == "ja2"
    w1['zwei']=d(und='noch weniger')
    yield from w1.wait()
    assert w1['zwei']['und'] == "noch weniger"
    assert w1['zwei'].get('und') == "noch weniger"

    logger.debug("Waiting for _update 2")
    yield from f
    assert m1.call_count == mc1
    assert m2.call_count == mc2+1

    # three ways to skin a cat
    del i0
    # w['zwei'].remove_monitor(i1) ## happened above
    i2.cancel()
    assert not w._later_mon
    assert not w['zwei']._later_mon
    assert not w['zwei']._get('und')._later_mon

    # _final=false means I can't add new untyped nodes
    types.register("**","new_a", cls=mtString)
    types.register("**","new_b", cls=mtString)
    w1._get('vier')._final = False
    mod = yield from t._f(d2,delete=True)
    yield from w1.wait(mod)
    w1['vier']['auch'] = "nein"
    #assert w1.vier.auch == "ja" ## should be, but too dependent on timing
    with pytest.raises(UnknownNodeError):
        w1['vier']['nix'] = "da"
    with pytest.raises(UnknownNodeError):
        yield from w1['vier'].set('nix', "da")
    w1['vier']['new_a'] = "e_a"
    yield from w1.wait()
    assert w1['vier']['auch'] == "nein"
    with pytest.raises(KeyError):
        assert w1['vier']['dud']
    assert w1['vier']['new_a'] == "e_a"

    d1=d(two=d(vier=d(a="b",c="d")))
    mod = yield from t._f(d1)
    yield from w1.wait(mod)
    assert w1['vier']['a'] == "b"
    with pytest.raises(KeyError):
        w1['vier']['new_b']

    # _final=true means external additions don't come through either
    w1._get('vier')._final = True
    d1=d(two=d(vier=d(c="x",d="y",new_b="z")))
    mod = yield from t._f(d1)
    yield from w1.wait(mod)
    assert w1['vier']['c'] == "x"
    with pytest.raises(KeyError):
        w1['vier']['d']
    with pytest.raises(UnknownNodeError):
        w1['vier']['nixy'] = "daz"
    with pytest.raises(UnknownNodeError):
        yield from w1['vier'].set('nixy', "daz")
    assert w1['vier']['new_b'] == "z"
    yield from w.wait(mod)

    assert len(w['vier']) == 7,list(w['vier'])
    s=set(w['vier'])
    assert 'a' in s
    assert 'auch' in s
    assert 'auck' not in s

    # now delete the thing
    yield from w['vier'].delete('a')
    yield from w['vier'].delete('auch')
    yield from w['vier'].delete('oder')
    yield from w['vier'].delete('c')
    yield from w['vier'].delete('d')
    yield from w['vier'].delete('new_a')
    yield from w['vier'].delete('new_b')
    m = yield from w['vier'].delete(recursive=False)
    yield from w.wait(m)
    with pytest.raises(KeyError):
        w['vier']

    yield from w.close()
    yield from w1.close()
    yield from w2.close()

@pytest.mark.run_loop
@asyncio.coroutine
def test_update_ttl(client, loop):
    d=dict
    t = client

    mod = yield from t._f(d(nice=d(t2="fuu",timeout=d(of="data"),nodes="too")))
    w = yield from t.tree("/nice")
    assert w['timeout']['of'] == "data"
    assert w['timeout'].ttl is None
    assert w['nodes'] == "too"
    mod = yield from w.set('some','data',ttl=1)
    assert w._get('nodes').ttl is None
    logger.warning("_SET_TTL")
    w._get('timeout').ttl = 1
    yield from w._get('t2').set_ttl(1)
    yield from w._get('t2').del_ttl()
    yield from w._get('nodes').set_ttl(1)
    logger.warning("_SYNC_TTL")
    yield from w.wait()
    logger.warning("_GET_TTL")
    assert w._get('timeout').ttl is not None
    assert w['nodes'] == "too"
    yield from w.wait(mod)
    assert w['some'] == "data"
    assert w._get('nodes').ttl is not None
    del w._get('nodes').ttl
    yield from asyncio.sleep(2, loop=loop)
    with pytest.raises(KeyError):
        w['timeout']
    with pytest.raises(KeyError):
        w['some']
    assert w['nodes'] == "too"
    assert w._get('nodes').ttl is None
    assert w._get('t2').ttl is None

    yield from w.close()

@pytest.mark.run_loop
@asyncio.coroutine
def test_create(client):
    t = client
    with pytest.raises(etcd.EtcdKeyNotFound):
        yield from t.tree("/not/here", immediate=True, static=True, create=False)
    w1 = yield from t.tree("/not/here", immediate=True, static=True, create=True)
    w2 = yield from t.tree("/not/here", immediate=True, static=True, create=False)

    w2 = yield from t.tree("/not/there", immediate=True, static=True)
    w3 = yield from t.tree("/not/there", immediate=True, static=True, create=False)
    w4 = yield from t.tree("/not/there", immediate=True, static=True)
    with pytest.raises(etcd.EtcdAlreadyExist):
        yield from t.tree("/not/there", immediate=True, static=True, create=True)

    yield from w1.close()
    yield from w2.close()
    yield from w3.close()
    yield from w4.close()

@pytest.mark.run_loop
@asyncio.coroutine
def test_append(client):
    t = client
    d=dict
    w = yield from t.tree("/two", immediate=False, static=False)
    d1=d(zwei=d(drei={}))
    mod = yield from w.update(d1)
    yield from w.wait(mod=mod)
    a,mod = yield from w['zwei'].set(None,"value")
    b,mod = yield from w['zwei']['drei'].set(None,{'some':'data','is':'here'})
    yield from w.wait(mod=mod)
    assert w['zwei'][a] == 'value'
    assert w['zwei']['drei'][b]['some'] == 'data'

    yield from w.close()

