PYTHON := .venv/bin/python

.PHONY: setup run test compile

setup:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -e .

run:
	$(PYTHON) smooth_caddy.py

test:
	$(PYTHON) -m unittest discover -s tests

compile:
	$(PYTHON) -m compileall -q smooth_caddy.py app tests

.PHONY: release
release:
	$(PYTHON) tools/build_release.py
