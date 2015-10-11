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
import logging
logger = logging.getLogger(__name__)
##BP

import pytest
import etcd
from dabroker.util import attrdict
from moatree.node import mtRoot,mtDir,mtInteger

from .util import cfg,client

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

    d=attrdict
    t = client
    d1=d(one="eins",two=d(zwei=d(und="drei"),vier="5"),x="y")
    client._f(d1)
    # basic access, each directory separately
    w = client.tree("/two",mtRoot, immediate=False, static=True)
    assert w.zwei.und == "drei"
    assert w.vier == "5"
    with pytest.raises(KeyError):
        w.x
    # basic access, read it all at once
    w2 = client.tree("/two",mtRoot, immediate=True, static=True)
    assert w2.zwei.und == "drei"
    assert w.vier == "5"
    assert w == w2

    client._f(d(two=d(sechs="sieben")))
    # use typed subtrees
    w3 = client.tree("/",rRoot, static=True)
    assert w3.two.vier == 5
    assert w3.two.sechs=="sieben"
    assert not w3.two == w2
    # which are different, but not because of the tree types
    w4 = client.tree("/",mtRoot, static=True)
    assert not w3 == w4
    assert w3.x == w4.x
    assert type(w3) is not type(w4)

    # check basic node iterator
    res=set()
    for k,v in w3.two:
        res.add(k)
    assert res == {"zwei","vier","sechs"}

def test_update_watch(client):
    """Testing auto-update, both ways"""
    d=attrdict
    t = client
    d1=d(one="eins",two=d(zwei=d(und="drei"),vier="fünf",sechs="sieben",acht=d(neun="zehn")))
    client._f(d1)
    w = client.tree("/two",mtRoot, immediate=False, static=False)
    assert w.sechs=="sieben"
    assert w.acht.neun=="zehn"
    d2=d(two=d(zwei=d(und="mehr"),vier=d(auch="xxx",oder="fünfe")))
    mod = client._f(d2,delete=True)
    w._watcher.sync(mod)
    assert w.zwei.und=="mehr"
    assert w.vier.oder=="fünfe"
    assert "oder" in w.vier
    assert "oderr" not in w.vier

    # Directly insert "deep" entries
    client.client.write(client._extkey('/two/three/four/five/six/seven'),value=None,dir=True)
    mod = client.client.write(client._extkey('/two/three/four/fiver'),"what").modifiedIndex
    w._watcher.sync(mod)
    # and check that they're here
    assert w.three.four.fiver == "what"
    assert isinstance(w.three.four.five.six.seven, mtDir)
    # The ones deleted by _f(…,delete=True) should not be
    with pytest.raises(KeyError):
        w.sechs
    with pytest.raises(KeyError):
        w.acht
    # deleting a whole subtree is not yet implemented
    with pytest.raises(NotImplementedError): # TODO
        del w.vier
    del w.vier.oder
    w._watcher.sync()
    w.vier
    w.vier.auch
    with pytest.raises(KeyError):
        w.vier.oder
    del w.vier.auch
    w._watcher.sync()
    with pytest.raises(KeyError):
        w.vier.auch
    # Now test that adding a node does the right thing
    w.vier.auch = "ja"
    w.zwei.und = "weniger"
    w.zwei.zehn=d(zwanzig=30,vierzig=d(fuenfzig=60))
    # TODO: test adding a hash = subtree
    w1 = client.tree("/two",mtRoot, immediate=True)
    assert w is w1
    w2 = client.tree("/two",mtRoot, static=True)
    assert w is not w2
    assert w.zwei.und == "weniger"
    assert w2.zwei.und == "weniger"
    assert w.zwei.zehn.zwanzig == "30"
    assert w2.zwei.zehn.zwanzig == "30"
    assert w.vier.auch == "ja"
    assert w2.vier.auch == "ja"

