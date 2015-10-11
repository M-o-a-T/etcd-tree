#!/usr/bin/make -f
##
##  Copyright © 2007-2012, Matthias Urlichs <matthias@urlichs.de>
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

export PYTHONPATH=$(shell pwd):$(shell pwd)/dabroker
DESTDIR ?= "/"
PYDESTDIR ?= ${DESTDIR}
PYTHON ?= python3

all: 
	$(PYTHON) setup.py build
install: 
	$(PYTHON) setup.py install --root="$(PYDESTDIR)" --no-compile -O0 --install-layout=deb

test: all test.cfg
	$(PYTHON) test/util.py
	py.test-3 --cov-report term-missing --cov-config .coveragerc --cov=moatree test/

test.cfg:
	@echo "You need to create a configuration file for testing." >&2
	@echo "Use test.cfg.sample as an example." >&2
	@exit 1
update:
	scripts/update_boilerplate

.PHONY: all install test update
