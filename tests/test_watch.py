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
from functools import partial
from etcd_tree.node import EtcRoot,EtcDir,EtcValue,EtcInteger,EtcFloat,\
                           EtcXValue,EtcString,EtcBoolean,EtcAwaiter, \
                           ReloadData,ReloadRecursive
from etcd_tree.etcd import EtcTypes,WatchStopped

from .util import cfg,client
from unittest.mock import Mock

class IntObj(EtcXValue):
    type = int

@pytest.mark.run_loop
async def test_basic_watch(client,loop):
    """Watches which don't actually watch"""
    # object type registration
    types = EtcTypes()
    twotypes = EtcTypes()
    @twotypes.register()
    class rTwo(EtcDir):
        pass
    class rDie(EtcValue):
        async def has_update(self):
            raise RuntimeError("RIP")
    @twotypes.register("die")
    class rPreDie(EtcValue):
        @classmethod
        async def this_obj(cls,recursive=None,**kw):
            return rDie(**kw)
    # reg funcion shall return the right thing
    types.step('two',dest=twotypes)
    assert types[('two','die')] is rPreDie
    assert types.lookup(('two','die'),dir=False) is rPreDie
    assert types.lookup('two','die',dir=False) is rPreDie
    assert types.lookup('two/die',dir=False) is rPreDie
    assert types.lookup('two',dir=True,raw=True).lookup('die',dir=False) is rPreDie
    assert types.lookup('two/die',dir=False,raw=True).lookup(dir=False) is rPreDie
    i = types.register("two","vier", cls=EtcBoolean)
    assert i is EtcBoolean
    i = types.register("*/vierixx")(EtcInteger)
    assert i is EtcInteger
    types['what/ever'] = EtcFloat
    assert types.lookup('what','ever', dir=False) is EtcFloat
    assert types['what/ever'] is EtcFloat
    with pytest.raises(AssertionError):
        types['/what/ever']
    with pytest.raises(AssertionError):
        types['what/ever/']
    with pytest.raises(AssertionError):
        types['what//ever']
    types['something/else'] = EtcInteger
    assert types['two/vier'] is EtcBoolean
    assert types['something/else'] is EtcInteger
    assert types['not/not'] is None

    d=dict
    t = client
    d1=d(one="eins",two=d(zwei=d(und="drei",a=d(b=d(c='d'))),vier="true"),x="y")
    await t._f(d1)
    # basic access, each directory separately
    class xRoot(EtcRoot):
        pass
    types.register(cls=xRoot)
    @xRoot.register("zwei","und")
    class xUnd(EtcString):
        pass
    w = await t.tree("/two", immediate=False, static=True, types=types)
    w.env.foobar="Foo Bar"
    assert sorted(dict((a,b) for a,b,c in w.registrations()).items()) == sorted([
           (('.',),xRoot),
           (('.', 'something', 'else'), EtcInteger),
           (('.', '*', 'vierixx'), EtcInteger),
           (('.', 'what', 'ever'), EtcFloat),
           (('.', 'two'), rTwo),
           (('.', 'two', 'die'), rPreDie),
           (('.', 'two', 'vier'), EtcBoolean),
           (('zwei', 'und'), xUnd),
    ]), list(w.registrations())
    assert isinstance(w,xRoot)
    assert w.env.foobar == "Foo Bar"
    assert w.env.barbaz is None
    assert w['zwei'].env is w.env
    assert w['zwei']['a']['b'].env is w.env

    assert w['zwei']['und'] == "drei"
    assert type(w['zwei']._get('und')) is xUnd
    assert w['vier'] == "true"
    with pytest.raises(KeyError):
        w['x']
    # basic access, read it all at once
    w2 = await t.tree("/two", immediate=True, static=True, types=types)
    assert w2['zwei']['und'] == "drei"
    assert w['vier'] == "true"
    assert w == w2

    # basic access, read it on demand
    w5 = await t.tree("/two", immediate=None, types=types)
    def wx(x):
        assert x.added == {'und','a'}
        x.test_called = 1
    mx = w5['zwei'].add_monitor(wx)
    assert isinstance(w5['zwei']['und'],EtcAwaiter)
    assert (await w5['zwei']['und']).value == "drei"
    assert w5['vier'] == "true"
    await w5['zwei'].force_updated()
    assert w5['zwei'].test_called

    # use typed subtrees
    w4 = await t.tree((), types=types)
    await w4.set('two',d(sechs="sieben"))
    w3 = await t.tree("/", static=True, types=types)
    assert w3['two']['vier'] is True
    assert w3['two']['sechs'] == "sieben"
    ##assert not w3['two'] == w2
    # which are different, but not because of the tree types
    assert not w3 is w4
    assert w3 == w4

    # check basic node iterators
    res=set()
    for v in w3['two']['zwei'].values():
        assert not isinstance(v,EtcValue)
        if not isinstance(v,EtcDir):
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
    await w4['two'].set('hello','one')
    await w4['two'].set('die','42')
    await asyncio.sleep(1.5, loop=loop)
    with pytest.raises(RuntimeError):
        await w4['two'].set('hello','two')
    
    await w.close()
    await w2.close()
    await w3.close()
    await w4.close()
    await w5.close()

@pytest.mark.run_loop
async def test_update_watch_direct(client):
    """Testing auto-update, both ways"""
    d=dict
    t = client
    wr,w = await t.tree("/", sub='two', immediate=False, static=False,update_delay=0.25)
    wi = await t.tree('/two', immediate=None)
    d2=d(two=d(zwei=d(und="mehr"),drei=d(cold="freezing"),vier=d(auch="xxx",oder="fünfe")))
    mod = await t._f(d2,delete=True)
    await wr.wait(mod=mod)

    with pytest.raises(KeyError):
        await w.subdir('zwei','drei','der', name=":tag", create=False)
    tag = await w.subdir("zwei/drei",name="der/:tag", create=True)
    tag2 = await w.subdir("zwei/drei/plus",name="auch/:tag", create=True)
    tug = await w.subdir("zwei/drei/vier",name="das/:tagg")
    tug = await w.subdir(('zwei','drei','vier'),name="das/:tagg")
    tugg = w.lookup(('zwei','drei','vier'),name="das/:tagg")
    assert tug is tugg
    tug2 = await w.subdir("zwei/drei/vier",name="das/:tagg")
    await tag.set("hello","kitty")
    await tag2.set("hello","friend")
    await tug.set("hello","kittycat")
    assert tug2['hello'] == 'kittycat'

    w['vier']
    w['vier']['auch']
    await w['vier'].delete('auch',prev='xxx')
    with pytest.raises(KeyError):
        w['vier']['auch']
    with pytest.raises(KeyError):
        w['zwei']['zehn']
    # Now test that adding a node does the right thing
    await w['vier'].set('auch',"ja1")
    await w['zwei'].set('zehn',d(zwanzig='30',vierzig=d(fuenfzig='60')))
    await w['zwei'].set('und', "weniger")

    assert w['zwei']['und'] == "weniger"
    assert w['zwei']['zehn']['zwanzig'] == "30"
    assert w['zwei']['zehn']['vierzig']['fuenfzig'] == "60"
    assert w['vier']['auch'] == "ja1"
    assert w['zwei']['drei']['der'][':tag']['hello'] == "kitty"
    await w.force_updated()
    n=0
    for k in w.tagged(':tag'):
        if k['hello']=='kitty':
            n |= 1
        elif k['hello']=='friend':
            n |= 2
        else:
            assert False,k['hello']
    assert n==3
    n=0
    for k in w.tagged(':tag',depth=3):
        n += 1
    assert n==0
    for k in w.tagged(':tag',depth=4):
        n += 1
        assert k['hello']=='kitty',k['hello']
    assert n==1
    n=0
    for k in w.tagged(':tag',depth=5):
        n += 1
        assert k['hello']=='friend',k['hello']
    assert n==1
    n=0
    for k in w.tagged(':tag',depth=6):
        n += 1
    assert n==0
    await tag2.delete(recursive=True)
    n = 0
    async for k in wi.tagged(':tag'):
        n += 1
        assert k['hello']=='kitty'
    assert n==1

    m = await w.delete('vier',recursive=True)
    await wr.wait(m)
    with pytest.raises(KeyError):
        w['vier']

    # etcd.EtcdNotFile is stupid. Bug in etcd (issue#4075).
    with pytest.raises((etcd.EtcdDirNotEmpty,etcd.EtcdNotFile)):
        del w['zwei']
        await wr.wait(m, tasks=True)
    await wr.wait(m, tasks=True)

    m = await w.delete('zwei', recursive=True)
    await wr.wait(m)
    with pytest.raises(KeyError):
        w['zwei']

    await wr.close()
    await wi.close()

@pytest.mark.run_loop
async def test_subdir(client, loop):
    """Testing auto-update, both ways"""
    logger.debug("START subdir")
    d=dict
    types = EtcTypes()
    t = client
    w = await t.tree(("two",), immediate=False, static=False)
    d1=d(bla=d(und="drei",oder={}),vier="fünf",sechs="sieben",acht=d(neun="zehn"))
    await w.update(d1)
    await w.close()

    w = await t.tree(("two",), immediate=None, static=False)
    assert isinstance(w['bla'],EtcAwaiter)
    wd = w['bla']['und']
    assert isinstance(wd,EtcAwaiter), wd
    wd = await wd
    assert isinstance(wd,EtcValue), wd
    await w.close()

def ilen(gen):
    n = 0
    for x in gen:
        n += 1
    return n

@pytest.mark.run_loop
async def test_pri(client, loop):
    """Testing prioritized reading"""
    logger.debug("START subdir")
    d=dict
    types = EtcTypes()
    t = client
    w = await t.tree(("two",), immediate=False, static=False)
    d1=d(pri=d(a="1",b="2",c="3",d="4",e="5"))
    await w.update(d1)
    await w.close()

    class CheckFirst(EtcString):
        async def init(self):
            assert ilen(self.parent.values()) == 1, self.parent._data
    class CheckLast(EtcString):
        async def init(self):
            assert ilen(self.parent.values()) == 5, self.parent._data
        
    types.register("pri","c",cls=CheckFirst,pri=1)
    types.register("pri","d",cls=CheckLast,pri=-1)
    types.register("pri","b",cls=CheckLast,pri=-1)
    w = await t.tree(("two",), immediate=None, static=False, types=types)
    wd = w['pri']
    assert isinstance(wd,EtcAwaiter)
    wd = await wd
    assert isinstance(wd,EtcDir), wd
    assert wd['a'] == "1"
    assert wd['b'] == "2"
    assert wd['c'] == "3"
    await w.close()

@pytest.mark.run_loop
async def test_update_watch(client, loop):
    """Testing auto-update, both ways"""
    logger.debug("START update_watch")
    d=dict
    types = EtcTypes()
    t = client
    w = await t.tree(("two",), immediate=False, static=False)
    d1=d(zwei=d(und="drei",oder={}),vier="fünf",sechs="sieben",acht=d(neun="zehn"))
    await w.update(d1)

    m1,m2 = Mock(),Mock()
    f = asyncio.Future(loop=loop)
    def wake(x):
        f.set_result(x)
    def mx(x):
        s = getattr(x,'test_step',0)
        x.test_step = s+1
        if s == 0:
            assert x.added == {'und','oder'}
            assert x.deleted == {'oder'}
        elif s == 1:
            assert x.added == {':zehn'}
            assert not x.deleted
        else:
            assert 0,s
        pass
    i0 = w.add_monitor(wake)
    i1 = w['zwei'].add_monitor(m1)
    ix = w['zwei'].add_monitor(mx)
    i2 = w['zwei']._get('und').add_monitor(m2)

    assert w['sechs'] == "sieben"
    acht = w['acht']
    assert acht['neun'] =="zehn"
    d2=d(two=d(zwei=d(und="mehr"),vier=d(auch="xxy",oder="fünfe")))
    mod = await t._f(d2,delete=True)
    await w.wait(mod=mod)
    assert w['zwei']['und']=="mehr"
    assert w['vier']['oder']=="fünfe"
    assert w['vier']['auch']=="xxy"
    assert "oder" in w['vier']
    assert "oderr" not in w['vier']

    # Directly insert "deep" entries
    await t.client.write(client._extkey('/two/three/four/five/six/seven'),value=None,dir=True)
    mod = (await t.client.write(client._extkey('/two/three/four/fiver'),"what")).modifiedIndex
    await w.wait(mod)
    # and check that they're here
    assert w['three']['four']['fiver'] == "what"
    assert isinstance(w['three']['four']['five']['six']['seven'], EtcDir)

    logger.debug("Waiting for _update 1")
    await f
    assert w['zwei'].test_step == 1
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
    with pytest.raises((etcd.EtcdDirNotEmpty,etcd.EtcdNotFile)):
        del w['vier']
        await w.wait(tasks=True)
    del w['vier']['oder']
    await w.wait(tasks=True)
    w['vier']
    s = w['vier']._get('auch')._cseq
    with pytest.raises(KeyError):
        w['vier']['oder']
    m = await w['vier']._get('auch').delete()
    await w.wait(m, tasks=True)
    with pytest.raises(KeyError):
        w['vier']['auch']

    # Now test that adding a node does the right thing
    m = await w['vier'].set('auch',"ja2")
    logger.debug("Set :zehn")
    w['zwei'][':zehn'] = d(zwanzig=30,vierzig=d(fuenfzig=60))
    w['zwei']['und'] = "weniger"
    logger.debug("WAIT FOR ME")
    await w['zwei'].wait(m,tasks=True)
    assert s != w['vier']._get('auch')._cseq

    from etcd_tree import client as rclient
    from .util import cfgpath
    tt = await rclient(cfgpath, loop=loop)
    w1 = await tt.tree("/two", immediate=True, types=types)
    assert w is not w1
    assert w == w1
    # wx = await tt.tree("/two", immediate=True)
    # assert wx is w1 ## no caching
    w2 = await t.tree("/two", static=True)
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
    assert w1['zwei'][':zehn']['zwanzig'] == "30"
    assert w2['zwei'][':zehn']['zwanzig'] == "30"
    assert w1['vier']['auch'] == "ja2"
    assert w2['vier']['auch'] == "ja2"
    w1['zwei']=d(und='noch weniger')
    await w1.wait(tasks=True)
    assert w1['zwei']['und'] == "noch weniger"
    assert w1['zwei'].get('und') == "noch weniger"

    logger.debug("Waiting for _update 2")
    await f
    assert w['zwei'].test_step == 2
    assert m1.call_count == mc1
    assert m2.call_count == mc2+1

    # three ways to skin a cat
    del i0
    # w['zwei'].remove_monitor(i1) ## happened above
    w['zwei'].remove_monitor(ix)
    i2.cancel()
    assert not w._later_mon
    assert not w['zwei']._later_mon
    assert not w['zwei']._get('und')._later_mon

    types.register("**","new_a", cls=IntObj)
    types.register(("**","new_b"), cls=EtcInteger)
    mod = await t._f(d2,delete=True)
    await w1.wait(mod, tasks=True)
    w1['vier']['auch'] = "nein"
    #assert w1.vier.auch == "ja" ## should be, but too dependent on timing
    w1['vier']['new_a'] = 4242
    await w1.wait(tasks=True)
    assert w1['vier']['auch'] == "nein"
    with pytest.raises(KeyError):
        assert w1['vier']['dud']
    assert w1['vier']['new_a'].value == 4242

    with pytest.raises(ValueError):
        await w1['vier'].set('new_a',"x123", ext=True)
    await w1['vier'].set('new_a',"123", ext=True)
    assert w1['vier']['new_a'].value == 123

    d1=d(two=d(vier=d(a="b",c="d")))
    mod = await t._f(d1)
    await w1.wait(mod, tasks=True)
    assert w1['vier']['a'] == "b"
    with pytest.raises(KeyError):
        w1['vier']['new_b']

    d1=d(two=d(vier=d(c="x",d="y",new_b=123)))
    mod = await t._f(d1)
    await w1.wait(mod, tasks=True)
    assert w1['vier']['c'] == "x"
    assert w1['vier']['d'] == "y"
    assert w1['vier']['new_b'] == 123
    await w.wait(mod, tasks=True)

    assert len(w['vier']) == 7,list(w['vier'])
    s=set(w['vier'])
    assert 'a' in s
    assert 'auch' in s
    assert 'auck' not in s

    # now delete the thing
    await w['vier'].delete('a')
    await w['vier'].delete('auch')
    await w['vier'].delete('oder')
    await w['vier'].delete('c')
    await w['vier'].delete('d')
    await w['vier'].delete('new_a')
    await w['vier'].delete('new_b')
    m = await w.delete('vier',recursive=False)
    await w.wait(m, tasks=True)
    with pytest.raises(KeyError):
        w['vier']
    with pytest.raises(RuntimeError):
        await w.delete()

    assert w.running
    assert not w.stopped.done()
    await t.delete("/two",recursive=True)
    await asyncio.sleep(0.3,loop=loop)
    assert not w.running
    assert w.stopped.done()

    await w.close()
    await w1.close()
    await w2.close()

@pytest.mark.run_loop
async def test_update_ttl(client, loop):
    d=dict
    t = client

    mod = await t._f(d(nice=d(t2="fuu",timeout=d(of="data"),nodes="too")))
    w = await t.tree("/nice")
    assert w['timeout']['of'] == "data"
    assert w['timeout'].ttl is None
    assert w['nodes'] == "too"
    mod = await w.set('some','data',ttl=2)
    assert w._get('nodes').ttl is None
    logger.warning("_SET_TTL")
    w._get('timeout').ttl = 1
    await w._get('t2').set_ttl(1)
    await w._get('t2').del_ttl()
    await w._get('nodes').set_ttl(1)
    logger.warning("_SYNC_TTL")
    await w.wait(tasks=True)
    logger.warning("_GET_TTL")
    assert w._get('timeout').ttl is not None
    assert w['nodes'] == "too"
    await w.wait(mod, tasks=True)
    assert w['some'] == "data"
    assert w._get('nodes').ttl is not None
    del w._get('nodes').ttl
    await asyncio.sleep(1.5, loop=loop)
    with pytest.raises(KeyError):
        w['timeout']
    await asyncio.sleep(1.0, loop=loop)
    with pytest.raises(KeyError):
        w['some']
    assert w['nodes'] == "too"
    assert w._get('nodes').ttl is None
    assert w._get('t2').ttl is None

    await w.close()

@pytest.mark.run_loop
async def test_ready(client, loop):
    d=dict
    t = client

    mod = await t._f(d(rdy=d(t2="fuu",nodes="too")))
    w = await t.tree("/rdy")
    mod = await w.set('some','data')
    mod = await w.set('other','data2')
    t1 = time.monotonic()
    x = w._get('some')
    y = w._get('other')
    assert not x.is_ready
    assert not y.is_ready
    assert not w.is_ready
    await y.delete(sync=False)
    a = 0
    async def w2(f,xx):
        await xx.ready
        nonlocal a
        a |= f
    f1 = w2(1,x)
    f2 = w2(2,y)
    f3 = w2(4,w)
    await asyncio.gather(f1,f2,f3, loop=loop)
    t2 = time.monotonic()
    assert a == 7, a
    assert 0.95 <= t2-t1 <= 2
    await w.close()

@pytest.mark.run_loop
async def test_task(client, loop):
    d=dict
    t = client
    w = await t.tree("/")

    xx = [0]
    async def one(x):
        x[0] += 1
    w.root.task(one,xx)

    assert xx[0] == 0, xx
    await w.wait(tasks=True)
    assert xx[0] == 1, xx
    w.root.task(one,xx)
    w.root.task(one,xx)
    await w.wait(tasks=True)
    assert xx[0] == 3, xx
    w.root.task(one,xx)
    await w.close()
    assert xx[0] == 4, xx

@pytest.mark.run_loop
async def test_create(client):
    t = client
    with pytest.raises(etcd.EtcdKeyNotFound):
        await t.tree("/not/here", immediate=True, static=True, create=False)
    w1 = await t.tree(('not','here'), immediate=True, static=True, create=True)
    w2 = await t.tree("/not/here", immediate=True, static=True, create=False)
    assert not w2.running
    assert w2.stopped.done()
    await w2.close()

    w2 = await t.tree("/not/there", immediate=True, static=True)
    w3 = await t.tree(('not','there'), immediate=True, static=True, create=False)
    w4 = await t.tree("/not/there", immediate=True, static=True)
    with pytest.raises(etcd.EtcdAlreadyExist):
        await t.tree("/not/there", immediate=True, static=True, create=True)

    await w1.close()
    await w2.close()
    await w3.close()
    await w4.close()

@pytest.mark.run_loop
async def test_append(client):
    t = client
    d=dict
    w = await t.tree("/two", immediate=False, static=False)
    d1=d(zwei=d(drei={}))
    mod = await w.update(d1)
    await w.wait(mod=mod)
    a,mod = await w['zwei'].set(None,"value")
    b,mod = await w['zwei']['drei'].set(None,{'some':'data','is':'here'})
    await w.wait(mod=mod)
    assert w['zwei'][a] == 'value'
    assert w['zwei']['drei'][b]['some'] == 'data'

    await w.close()

@pytest.mark.run_loop
async def test_typed_basic(client,loop):
    """Watches which don't actually watch"""
    await do_typed(client,loop,False,False)

@pytest.mark.run_loop
async def test_typed_recursed(client,loop):
    """Watches which don't actually watch"""
    await do_typed(client,loop,False,True)

@pytest.mark.run_loop
async def test_typed_preload(client,loop):
    """Watches which don't actually watch"""
    await do_typed(client,loop,False,None)

@pytest.mark.run_loop
async def test_typed_subtyped(client,loop):
    """Watches which don't actually watch"""
    await do_typed(client,loop,True,False)

@pytest.mark.run_loop
async def test_typed_recursed_subtyped(client,loop):
    """Watches which don't actually watch"""
    await do_typed(client,loop,True,True)

@pytest.mark.run_loop
async def test_typed_preload_subtyped(client,loop):
    """Watches which don't actually watch"""
    await do_typed(client,loop,True,None)

async def do_typed(client,loop, subtyped,recursed):
    # object type registration
    types = EtcTypes()
    if subtyped:
        class Sub(EtcDir):
            def __init__(self,*a,pre=None,**k):
                super().__init__(*a,**k,pre=pre)
                assert pre['my_value'].value == '10'
                self._types = EtcTypes()
                self._types.register('my_value',cls=EtcInteger)
            def subtype(self,*path,pre=None,recursive=None,**kw):
                if path == ('my_value',):
                    if pre is None:
                        raise ReloadData
                    assert pre.value=="10",pre
                elif path == ('a','b','c'):
                    if pre is None:
                        raise ReloadData # yes, I'm bad
                    elif not recursive:
                        raise ReloadRecursive
                elif not recursive:
                    assert len(path)<3
                return super().subtype(*path,pre=pre,recursive=recursive,**kw)
        types.register('here',cls=Sub)
    else:
        types.register('here','my_value',cls=EtcInteger)

    d=dict
    t = client
    d1=d(types=d(here=d(my_value='10',a=d(b=d(c=d(d=d(e='20')))))))
    await t._f(d1)
    w = await t.tree("/types", immediate=recursed, static=True, types=types)
    v = await w['here']._get('my_value')
    assert v.value == 10,w['here']._get('my_value')
    v = await w['here']
    assert v['my_value'] == 10, v._get('my_value')
    assert (recursed is None) == (type(v['a']['b']['c']) is EtcAwaiter)
    await v['a']['b']['c']
    assert not type(v['a']['b']['c']) is EtcAwaiter
    assert (type(v['a']['b']['c']['d']) is EtcAwaiter) == (recursed is None and not subtyped)
    await v['a']['b']['c']['d'] # no-op
    assert v['a']['b']['c']['d']['e'] == '20'
    assert isinstance(v, Sub if subtyped else EtcDir)

    await w.close()
