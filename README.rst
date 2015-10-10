===========
The MoaTree
===========

This subproject implements access to etcd. Specifically, it auto-generates
an object tree from some `etcd` space and allows you to modify that tree.

This is supposed to be mostly seamless, in that a change *here* will be
reflected *there* without requiring you to manage all that tedious
communication.

`etcd` has a couple of advantages; among others, replication is really easy
to set up and its data can be controlled with simple HTTP requests. On the
downside, there's no atomicity and no structured data. To help with the
first shortcoming, some advisory locking is planned.

The asynchronous nature of etcd updates means that any change to a MoaTree
object will not be visible immediately. You will, however, get an exception
if it could not be applied to the etcd tree. All changes will include etcd's 
modification index, thus overwriting unrelated changes won't happen.

-------
Testing
-------

I'm aiming for 100% test coverage.

Helper scripts
--------------

There are a couple of low-level scripts:

* etcd2yaml

  dumps an etcd subtree to a YAML file

* yaml2etcd

  stores a YAML file (don't use arrays!) into an etcd subtree, optionally
  obliterating anything else in there

* etcdmon

  monitors an etcd subtree for changes


