.PHONY: lint fix

lint:
	ruff check .
	ruff format --check .

fix:
	ruff check --fix .
	ruff format .
