.PHONY: test sync deploy budget

test:
	python3 -m unittest discover -s tests -v

sync:
	python3 scripts/sync_lambda.py

deploy:
	./scripts/deploy.sh

# make budget EMAIL=tuaemail@example.com
budget:
	@test -n "$(EMAIL)" || (echo "Richiesto EMAIL=tuaemail@example.com" >&2; exit 2)
	./scripts/deploy_budget.sh "$(EMAIL)"
