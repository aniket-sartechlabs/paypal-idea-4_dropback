PYTHON ?= python3
VENV_PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python)

.PHONY: setup dev api frontend watch test sandbox-check sandbox-buyer sandbox-demo demo-video-check demo-video submission-check

setup:
	$(VENV_PY) scripts/tasks.py setup

dev:
	$(VENV_PY) scripts/tasks.py dev

api:
	$(VENV_PY) scripts/tasks.py api

frontend:
	$(VENV_PY) scripts/tasks.py frontend

watch:
	$(VENV_PY) scripts/tasks.py watch

test:
	$(VENV_PY) scripts/tasks.py test

sandbox-check:
	$(VENV_PY) scripts/tasks.py sandbox-check

sandbox-buyer:
	$(VENV_PY) scripts/tasks.py sandbox-buyer $(ARGS)

sandbox-demo:
	$(VENV_PY) scripts/tasks.py sandbox-demo $(ARGS)

demo-video-check:
	$(VENV_PY) scripts/tasks.py demo-video-check $(ARGS)

demo-video:
	$(VENV_PY) scripts/tasks.py demo-video $(ARGS)

submission-check:
	$(VENV_PY) scripts/tasks.py submission-check
