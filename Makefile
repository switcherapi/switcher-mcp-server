.PHONY: install lint test cover e2e-tools e2e-prompts

install:
	pipenv install --dev

lint:
	pipenv run python -m pylint switcher_mcp_server

test:
	pipenv run pytest -v --cov=./switcher_mcp_server --cov-report xml --cov-config=.coveragerc

cover:
	pipenv run coverage html

e2e-tools:
	pipenv run python scripts/e2e/flows/tools_validation.py

e2e-prompts:
	pipenv run python scripts/e2e/flows/prompt_validation.py

run:
	pipenv run python -m switcher_mcp_server.server --transport streamable-http --host 0.0.0.0 --port 8000
