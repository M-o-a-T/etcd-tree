=======================
Pythonic access to etcd
=======================

This subproject implements access to etcd. Specifically, it auto-generates
an object tree from some place within your `etcd` hierarchy and allows you
to modify that tree.

This is supposed to be mostly seamless, in that a change *here* will be
reflected *there* without requiring you to manage all that tedious
communication.

.. image:: https://travis-ci.org/M-o-a-T/etcd_tree.png?branch=master
   :target: https://travis-ci.org/M-o-a-T/etcd_tree

.. image:: https://coveralls.io/repos/M-o-a-T/etcd_tree/badge.svg?branch=master&service=github
   :target: https://coveralls.io/github/M-o-a-T/etcd_tree?branch=master


`etcd` has a couple of advantages; among others, replication is really easy
to set up and its data can be controlled with simple HTTP requests. On the
downside, there's no atomicity and no structured data. To help with the
first shortcoming, some advisory locking is planned.

The asynchronous nature of etcd updates means that any change to a etcd_tree
object will not be visible immediately. You will, however, get an exception
if it could not be applied to the etcd tree. All changes will include etcd's 
modification index, thus overwriting unrelated changes won't happen.

See the *TUTORIAL* document for a quick introduction.

-----
Tools
-----

There's a little GTK program to show your etcd tree in real time.
You can also monitor things from the command line.

A couple of scripts are included to dump etcd to YAML, and vice versa.

-------
Testing
-------

I'm aiming for 100% test coverage.

Yes, for real.

If you fix a bug, please include a test that would have triggered the bug.
Enhancements should obviously actually exercise them.

Helper scripts
--------------

There are a couple of low-level scripts:

* etcd2yaml

  dumps an etcd subtree to a YAML file

* yaml2etcd

  stores a YAML file (don't use arrays!) into an etcd subtree, optionally
  obliterating anything else in there

* etcdmon

  monitors an etcd subtree for changes, emitting them to the console.
  
* etcd-tree

  Visually monitors an etcd subtree for changes. Read-only (for now).

  This script requires a current version of python-gi, which (as of
  2016-01) is not yet available in a released version of Debian or Ubuntu.

