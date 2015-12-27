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

* One call per etcd directory. This is the default.

* All at once. Use ``.tree(…, immediate=True)``. Do this if your subtree
  isn't too large.

* Later. Data which haven't been accessed yet are replaced with an
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

  … will raise an error in the ``await`` call if the directory
  ``/where/ever/some/where`` does not actually exist.

Subsequent changes on data which you have not yet accessed are
**not** processed and your code will **not** be notified when they happen.

An ``EtcAwaiter`` is an incomplete placeholder. Specifically, you cannot set
any values on it. This is intentional.

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
'**' does not match an empty path; if you need that too, do a secoond
registration without the '**' component. More specific matches are
of course preferred. However, if you do something like registering both
``('**','three')`` and ``('*',two,'*')`` to different classes,
matching ``('one','two','three')`` to that will result in one or
the other, but which one is undefined and may change without notice.
Use a typed subdirectory to resolve the conflict (below).

If you want to subclass a whole directory, derive your class from
``EtcDir``. 

    class myDir(EtcDir):
        my_data=the_data
    types.register(…, cls=myDir)

    class 

If you need access to private data, you can to pass an environment to ``.tree()``:

.. code:: python

    the_data = …whatever…
    view = await client.tree("/num",types=types,env=the_data)

    class myDir(EtcDir):
        def some_method(self):
            assert self.env is the_data

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

Sometimes you need to dynamically decide which subclass to use, based on
the actual data. To do that, register a subclass of ``mtTypedDir`` to a
node.

.. code:: python

    class myTypedDir(mtTypedDir):
        @classmethod
        def selftype(cls,parent,name,pre=None):
            if pre and pre['special'] == "special data":
                return SpecialClass
            return cls

        def __init__(self,*a,pre=None,**kw):
            super().__init__(*a,**kw) ##*
            self._types = EtcTypes()
            self._types.register(…)

        def subtype(self,*path,dir=None,pre=None): ##*
            if path == ('special','subdir') and pre['data'] == 'hello':
                return HelloData
            return super()(*path,dir=dir,pre=pre) ##*

Three things are going on here.

The ``selftype`` classmethod is called when instantiating the typed
subclass itself. ``pre`` is a dict with the raw data from etcd. You can
return any class you like, though it must be a subclass of ``mtTypedDir``.
The default is to use the class itself. 

``.subtype()`` is called for each entry. ``pre`` is the unprocessed content
of the etcd tree *relative to that entry*. If you need to base your
decision on data somewhere else, save it to a local attribute in
``__init__()``. The default implementation uses ``self._types`` for looking
up entries relative to your class; it defaults to the tree's types if no
match is found.

Currently, this method has three limitations.

etcd_tree does not support dynamically rebuilding your typed tree if the
data you based your typing decision on subsequently changes; you'll have to
do that yourself, which is non-trivial.

Nested ``mtTypedDir`` instances are not supported. This is unlikely to
change.

The data for typed directories is read all at once. You should probably
avoid doing this with large etcd trees.

