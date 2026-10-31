SHELL := /bin/bash
PYTHON ?= python
TEST_ENV ?= .test
TEST_PYTHON = $(abspath $(TEST_ENV))/bin/python

.PHONY: build clean test upload
build: clean
	$(PYTHON) -m build

clean:
	rm -rf dist *.egg-info build

test: build
	$(PYTHON) -m twine check dist/*
	$(PYTHON) -m virtualenv --copies $(TEST_ENV)
	$(TEST_PYTHON) -m pip install dist/*.whl pytest pytest-cov
	cd $(TEST_ENV) && $(TEST_PYTHON) -m pytest -c $(CURDIR)/pytest.ini $(CURDIR)/tests

upload: build
	$(PYTHON) -m twine check dist/*
	$(PYTHON) -m twine upload dist/*
