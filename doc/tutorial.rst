========
Tutorial
========

First, connect to etcd:

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
hierarchy this way, too:

.. code:: python

	view = client.tree("/more/data")
	assert len(view) == 0
	mod = await client.set("/more/data/for/Fred","intersting")

	await view.sync(mod)

	assert "for" in view
	assert "Fred" in view['for']
	assert view['for']['Fred'] == 'intersting'

	v = view['for']._get('Fred'); await v.set('interesting')
	await view['for'].set('Fred','interesting') # same thing
	view['for']['Fred'] = "interesting"; await view.sync() # that too

	assert (await client.get("/more/data/for/Fred")) == "interesting"

The object view always reflects the actual contents of the etcd server.
The first ``view.sync()`` waits for your change to arrive. Alternately we
could have waited a second or two, but that's bad form when testing.

The three lines which correct the speling misteak do the same thing in
different ways. The first accesses the underlying value object. The third
uses synchronous code to modify your data and sends your change to the
server later.

`etcd-tree` makes sure that the server's view of the object hierarchy matches
yours. Thus, if Fred already corrected the mistake but you didn't yet get
the update, your change will fail. Thus, you should avoid the
synchronous-code version if possible. (This will be revisited as soon as
etcd learns about transactional updates, which should happen sometime in
2016.)

Now, strings are boring. Fortunately, we can define our own (atomic) types.

.. code:: python

	from etcd_tree.node import mtFloat

	types = etcd.EtcTypes()
	types.register('number','**','is', cls=mtInteger)

	view = await client.tree("/num",types=types)
	await client.set("/num/number/wilma/is","42")
	mod = await client.set("/num/number/here/and/today/is","20151213")
	await view.sync(mod)
	assert view['number']['wilma']['is'] == 42

Special type nodes are '*' and '**', which do what you'd expect.
'**' does not match an empty path; if you need that too, do a secoond
registration.

If you want to subclass a whole directory, derive your class from
``mtDir``. There's no way to pass private data to your class constructor;
one workaround is to create a local class with your data in it:

.. code:: python

	the_data = …whatever…

	class myDir(mtDir):
		my_data=the_data
	types.register(…, cls=myDir)

	class 

Watching out for changes on your object is pretty straightforward: override
the ``has_update()`` method. Alternately you can attach a monitor function
to a node by using ``add_monitor()``, which expects a one-argument callback
(the node you're attaching the callback to) and returns an object with a
``.cancel()`` method if you're no longer interested.

Both methods will get called some time after "their" node, or any child node,
is changed, which includes additions or deletions. You can recognize being
deleted by checking whether your ``.seq`` attribute is ``None``.

A node's update handlers will only get called some time after those of
their child nodes have run. This can lead to starvation if you have a high
rate of change. This problem will be addressed in a future update.

