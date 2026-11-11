PYTHON ?= python3
VENV_PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python)

.PHONY: setup dev frontend test sandbox-check sandbox-buyer demo-video-check demo-video

setup:
	$(VENV_PY) scripts/tasks.py setup

dev:
	$(VENV_PY) scripts/tasks.py dev

frontend:
	$(VENV_PY) scripts/tasks.py frontend

test:
	$(VENV_PY) scripts/tasks.py test

sandbox-check:
	$(VENV_PY) scripts/tasks.py sandbox-check

sandbox-buyer:
	$(VENV_PY) scripts/tasks.py sandbox-buyer $(ARGS)

demo-video-check:
	$(VENV_PY) scripts/tasks.py demo-video-check $(ARGS)

demo-video:
	$(VENV_PY) scripts/tasks.py demo-video $(ARGS)
