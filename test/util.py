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

from dabroker.util import attrdict
import os
from yaml import safe_load
from yaml.constructor import SafeConstructor

__ALL__ = ('cfg',)

# monkeypatch YAML to return attrdicts
def construct_yaml_attrmap(self, node):
    data = attrdict()
    yield data
    value = self.construct_mapping(node)
    data.update(value)
SafeConstructor.add_constructor(
        'tag:yaml.org,2002:map',
        construct_yaml_attrmap)

# load a config file
def load_cfg(cfg):
    if os.path.exists(cfg):
        pass
    elif os.path.exists(os.path.join("tests",cfg)):
        cfg = os.path.join("tests",cfg)
    elif os.path.exists(os.path.join(os.pardir,cfg)):
        cfg = os.path.join(os.pardir,cfg)
    else:
        raise RuntimeError("Config file '%s' not found" % (cfg,))

    with open(cfg) as f:
        return safe_load(f)


if __name__ == "__main__":
    # quick&dirty test
    cfg = load_cfg("test.cfg.sample")
    d = attrdict
    d = d(config=d(etcd=d(host='localhost',port=2379,root='/test/moatree'),config='/config'))
    assert cfg == d, (cfg,d)
else:
    cfg = load_cfg(os.environ.get('MOATREE_TEST_CFG',"test.cfg"))

