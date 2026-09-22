# Relay — an ITSM service desk
#
#   make setup   install both halves
#   make dev     API on :8000 and the Vite dev server on :5173
#   make test    the backend suite
#   make serve   one process: build the frontend, serve it from the API
#   make import  load the Kaggle history into the database (see README)
#   make replay  put ~100 real ABC Tech tickets on the live desk (after import)
#   make backtest  score the escalation prediction against known outcomes
#
.DEFAULT_GOAL := help
PY := backend/.venv/bin/python
PORT ?= 8010

help:
	@grep -E '^[a-z-]+:' Makefile | grep -v grep | sed 's/:.*//' | sed 's/^/  make /'

setup: setup-api setup-web

setup-api:
	cd backend && uv venv .venv --python 3.12 && uv pip install -e ".[dev]" --python .venv/bin/python

setup-web:
	cd frontend && npm install

api:
	cd backend && .venv/bin/uvicorn relay.main:app --reload --port $(PORT)

web:
	cd frontend && npm run dev

dev:
	@echo "API on http://127.0.0.1:$(PORT) and the app on http://localhost:5173"
	@trap 'kill 0' INT TERM; \
	(cd backend && .venv/bin/uvicorn relay.main:app --reload --port $(PORT)) & \
	(cd frontend && npm run dev) & \
	wait

build:
	cd frontend && npm run build

serve: build
	@echo "Everything on http://127.0.0.1:$(PORT)"
	cd backend && .venv/bin/uvicorn relay.main:app --port $(PORT)

test:
	cd backend && .venv/bin/python -m pytest -q

import:
	cd backend && .venv/bin/python -m relay.import_history

replay:
	cd backend && .venv/bin/python -m relay.replay

backtest:
	cd backend && .venv/bin/python -m relay.backtest --n 60 --all

reset:
	rm -f backend/relay.db
	@echo "database dropped; it reseeds on the next start"

.PHONY: help setup setup-api setup-web api web dev build serve test import replay backtest reset
