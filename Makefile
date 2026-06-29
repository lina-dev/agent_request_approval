.PHONY: dev down test test-go test-py lint plan

dev:
	docker compose up -d

down:
	docker compose down

test: test-go test-py

test-go:
	cd services/go && go vet ./... && go test ./...

test-py:
	cd services/py && . .venv/bin/activate && python -m pytest -q

lint:
	cd services/go && go vet ./...
	cd services/py && . .venv/bin/activate && ruff check reimb tests

eval:
	cd services/py && . .venv/bin/activate && python -c "from reimb.graph.build import build_graph; from reimb.eval.runner import run_eval, assert_thresholds; m=run_eval(build_graph(),'eval/gold/cases.jsonl'); print(m); assert_thresholds(m)"

plan:
	cd infra && terraform init -backend=false && terraform validate
