========
Tutorial
========

First steps
-----------

Connect to etcd:

.. code:: python

    import etcd_tree.etcd as etcd

    client = etcd.EtcClient(root="/my/test", host="localhost")
    # arguments: see aio_etcd.client.Client

    await client._init()

This will access the hierarchy under that root (and create an empty
directory if that doesn't yet exist). You can now manually manipulate that
tree

.. code:: python

    await client.set("/some/data","some value")
    assert (await client.get("/some/data")) == "some value"
    await client.delete("/some/data")

but that's not very interesting. However, we can access the object
hierarchy another way, too:

.. code:: python

    view = client.tree("/more/data")
    assert len(view) == 0
    mod = await client.set("/more/data/for/Fred","intersting")

    await view.sync(mod)

    assert "for" in view
    assert "Fred" in view['for']
    assert view['for']['Fred'] == 'intersting'

    # Now fix the data
    await view['for'].set('Fred','interesting')
    v = view['for']._get('Fred'); await v.set('interesting')
    view['for']['Fred'] = "interesting"; await view.sync()

    # …  and check that it's there
    assert (await client.get("/more/data/for/Fred")) == "interesting"

The object view always reflects the actual contents of the etcd server.
The first ``view.sync()`` waits for your change to arrive in the view.
Alternately we could have waited a second or two, but that's bad form when
testing.

The three lines which correct the speling misteak do the same thing in
different ways. The first is preferred in an async context. The second
way accesses the data item's underlying ``EtcValue`` object. The third
uses synchronous code to modify your data and sends your change to the
server later.

`etcd-tree` makes sure that the server's view of the object hierarchy matches
yours. Thus, if Fred already corrected the mistake but you didn't yet get
the update, your change will fail and any later changes will be ignored.
Thus, you should avoid the synchronous-code version if possible.

Setting up
----------

There are three ways to read the initial object tree:

* One call per etcd directory. This is the default. It's safe but will take
  some time if your tree is large(ish).

* All at once. Use ``.tree(…, immediate=True)``. Do this if your subtree
  isn't too large.

* On demand. Data which haven't been accessed yet are replaced with an
  ``EtcAwaiter`` placeholder.

  .. code:: python

      # assume contents: /the/answer/is => unknown
      root = client.tree('/', immediate=None)
      data = root['the']['answer']
      # data.set('is',42) ## this code may fail
      data = await data
      assert data['is'] == 'unknown'
      await data.set('is',42) # now it won't

      # … or …
      data = root['the']['answer']['is']
      data = await data
      assert isinstance(data,EtcValue)
      assert data.value == 'unknown'
      await data.set(42)

      if type(data) is EtcAwaiter:
          data = await data
          if isinstance(data,EtcDir):
              # all non-directory children of this directory
              # will be accessible directly
              pass
          if isinstance(data,EtcValue):
              data = data.value
  
  Note that this code …

  .. code:: python

      root = client.tree('/where/ever', immediate=None)
      data = root['some']['where']
      data = await data

  … will raise an error in the ``await`` call if the etcd directory
  ``/where/ever/some/where`` does not actually exist.

Subsequent changes on data which you have not yet accessed are
**not** processed and your code will **not** be notified when they happen.

An ``EtcAwaiter`` is a placeholder. You can't so anything with it except
await it and look up subdirectories (which will also be ``EtcAwaiter``
instances until awaited-for).

`etcd-tree` guarantees that no data you've loaded will ever be replaced
with an ``EtcAwaiter``. Also, an update which directly adds new data to
something you already have awaited will add the actual data.

Data typing
-----------

Strings are boring. Fortunately, we can define our own (atomic) types.

.. code:: python

    from etcd_tree.node import EtcFloat

    types = etcd.EtcTypes()
    types.register('number','**','is', cls=EtcInteger)

    view = await client.tree("/num",types=types)
    await client.set("/num/number/wilma/is","42")
    mod = await client.set("/num/number/here/and/today/is","20151213")
    await view.sync(mod)
    assert view['number']['wilma']['is'] == 42

Special type nodes are '*' and '**', which do what you'd expect.
'**' does not match an empty path; if you need that too, do a second
registration without the '**' component.

More specific matches are preferred. However, if you do something like
registering both ``('**','three')`` and ``('*',two,'*')`` to different
classes, matching ``('one','two','three')`` to that will result in one or
the other, but which one is undefined and may change without notice.
Use a typed subdirectory to resolve the conflict (below).

Wildcards do not apply to names starting with a colon.

If you want to subclass a directory, derive your class from
``EtcDir``. 

    class myDir(EtcDir):
        my_data=the_data
    types.register(…, cls=myDir)

    class 

If you need access to private data, the tree has an ``env`` attribute. You
can set any attribute on that. Entries' ``env`` attributes mirror the root,
i.e. ``something.root.env is something.env``.

The ``env`` attribute is written so that you cannot replace its attributes.
Non-existing attributes will return None instead of raising an exception.

.. code:: python

    the_data = …whatever…
    view = await client.tree("/num",types=types)
    view.env.my_data = the_data
    with assert_error(RuntimeError):
        view.env.my_data = "foo"

    class myDir(EtcDir):
        def some_test_method(self):
            assert self.env.my_data is the_data
        def has_update(self):
            the_data = self.env.my_data
            if the_data:
                the_data.has_update(self) # or whatever

Monitoring for changes
----------------------

Watching out for changes on your object is pretty straightforward: override
the ``has_update()`` method. Alternately you can attach a monitor function
to a node by using ``add_monitor()``, which expects a one-argument callback
(the node you're attaching the callback to) and returns an object with a
``.cancel()`` method if you're no longer interested.

Both methods will get called some time after "their" node, or any child node,
is changed, which includes additions or deletions. You can recognize the
first call after initialization by testing ``self.notify_seq`` for zero,
and being deleted by checking ``self.seq`` for ``None``.

A node's update handlers will only get called some time after those of
their child nodes have run. This can lead to starvation if you have a high
rate of change. This problem will be addressed in a future update.
You can call ``.tree(…, update_delay=x)`` with x somewhat lower than
1 second (the default). This should be at least twice the time your etcd
requires to update a value.

Dynamic types
-------------

Sometimes you need to dynamically decide which subclass to use, based on
the actual data. To do that, register a subclass of ``EtcDir`` to a
node.

.. code:: python

    class HelloData(EtcString):
        pass

    class myTypedDir(EtcDir):
        def __init__(self,*a,pre=None,**kw):
            super().__init__(*a,**kw) ##*
            self._types = EtcTypes()
            self._types.register(…)

        def subtype(self,*path,dir=None,pre=None): ##*
            if path == ('special','subdir') and pre['data'] == 'hello':
                return HelloData
                # This will use HelloData for <self>/special/subdir
                # if its 'data' entry contains 'hello'
            return super().subtype(*path,dir=dir,pre=pre) ##*

``.subtype()`` is called for each entry below your node for which a type
needs to be looked up. ``pre`` is the content of the etcd tree *relative to
that entry*. The default implementation uses ``self._types`` for looking
up entries relative to your class.

``pre`` may be ``None``, in which case the data haven't been read yet;
raise ``ReloadData`` if you need that. The ``recursive`` parameter tells
you whether ``pre`` contains just the top-level directory or the whole
sub-hierarchy; raise ``ReloadRecursive`` if you need the latter.

``.subtype()`` recurses to the parent directory when the first
character of the entry's name is not a colon. You can
override this with the ``_types_from_parent`` attribute if necessary.

There is an alternate way to do this: you can teach a class to
instantiate another class instead.

.. code:: python

    class Cls_foo(EtcDir):
        pass

    class Some_cls(EtcDir):
        @classmethod
        async def this_obj(cls, **kw):
            name = pre.key.rsplit('/',1)[1].lower()
            m = globals().get('Cls_'+name,cls)
            return m(**kw)

If you register ``Some_cls`` at some path (via wildcard, otherwise this
exercise is useless …) and name the member ``foo``, You'll get a
``Cls_foo`` instance instead.

`etcd-tree` lets you create a directory type which auto-loads all of its
descendents. This is very useful for structured data which you'd like to
use in synchronous code.

.. code:: python

    from etcd_tree import EtcDir, ReloadRecursive
    class recEtcDir(EtcDir):
        """an EtcDir which always loads its content up front"""
        @classmethod
        async def this_obj(cls, recursive, **kw):
            if not recursive:
                raise ReloadRecursive
            return (await super().this_obj(recursive=recursive, **kw))

        async def init(self):
            self.force_updated()
            await super().init()

Type borders
------------

A fairly typical use of etcd is to have a hierarchy of
things-with-attributes. This begs the question of how to determine where
the hierarchy ends and the actual things start.

The common way to do this in ``etcd_tree`` is to tag this border with a
special name that starts with a colon (a "tagged" node). Obviously you'd
also register the thing's type for that tag.

``etcd_tree`` supports this convention:

* Type lookups don't propagate beyond tagged nodes.
  You can override this by setting the node's ``_types_from_parent``
  attribute.

* Update notifications within a tagged node don't propagate (and thus
  delay) beyond that node.
  You can override this by setting the node's ``_propagate_updates``
  attribute.
  
  Parents are still notified when a tagged node is created or deleted.
  Note that the "created" notification may run too early. In that case,
  call the parent's update handler yourself, from the tagged node's
  ``has_update()`` method.

* the ``EtcDir.tagged(TAG)`` method iterates all tagged nodes in a hierarchy,
  skipping subtrees with different tags. You can use a sync or async loop;
  however, the former will raise an error if you have non-awaited
  ``EtcAwaiter`` nodes in the hierarchy. You can also use this method to
  find all nodes with any tag (tag=True) or any non-tag name (tag=False),
  optionially limited to a specific tree depth (depth=N).

* Wildcard type lookups don't apply to tags. If you want to apply a class
  to any tag, use ':\*'. There is no tagged equivalent to '**'.

Misc
----

`etcd-tree` does not support dynamically rebuilding your typed tree if the
data you based your typing decision on subsequently changes. The best way
to fix that is to throw away the subtree and re-create it; to do this,
calling ``.throw_away()`` on a directory will replace it with an
EtcAwaiter object which you can then resolve by ``await``-ing on it.

`etcd-tree` hacks a couple of special methods into etcd's objects to make
working with them easier:

* ``.name`` is a property which contains the last part of the key.

* ``.child_nodes`` is an iterator which returns all direct descendants
  of a directory. It does not return ``self``, it does not skip
  directories, and it does not recurse into them.

* Finally, ``[name]`` will return the child whose name is ``name``. This is
  done by scanning; if you process a large directory, you should store
  the name>node association in a dict beforehand.

