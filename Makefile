.PHONY: help db-up db-down install init-db ingest-county ingest-tract status test lint

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

db-up: ## start local Postgres
	docker compose up -d --wait

db-down: ## stop local Postgres (keeps volume)
	docker compose down

install: ## install package + dev deps
	pip install -e ".[dev]"

init-db: ## apply schema + views
	python -m pgbigdata.cli init-db

ingest-county: ## ingest 2022 ACS5 at county level (single API call)
	python -m pgbigdata.cli ingest-acs --year 2022 --geography county

ingest-tract: ## ingest 2022 ACS5 at tract level (chunked per state)
	python -m pgbigdata.cli ingest-acs --year 2022 --geography tract

status: ## show recent load runs
	python -m pgbigdata.cli status

test: ## run unit tests (no DB/network needed)
	pytest -q

lint: ## ruff check
	ruff check src tests
