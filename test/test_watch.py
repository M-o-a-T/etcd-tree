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
from moatree.node import mtDir

from .util import cfg,client

def test_basic_watch(client):
    d=attrdict
    t = client
    d1=d(one="eins",two=d(zwei=d(und="drei"),vier="fünf"),x="y")
    client._f(d1)
    w = client.watch("/two",mtDir, immediate=False)
    assert w.zwei.und == "drei"
    assert w.vier == "fünf"
    with pytest.raises(KeyError):
        w.x
    w2 = client.watch("/two",mtDir, immediate=True)
    assert w2.zwei.und == "drei"
    assert w == w2
    client._f(d(two=d(sechs="sieben")))
    w3 = client.watch("/two",mtDir)
    assert w3.vier == "fünf"
    assert w3.sechs=="sieben"
    assert not w3 == w2


