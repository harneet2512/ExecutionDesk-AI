.PHONY: bootstrap dev test test-cov clean

bootstrap:
	@bash scripts/bootstrap.sh

dev:
	@bash scripts/dev.sh

test:
	@bash scripts/test.sh

test-cov:
	@bash scripts/test.sh --cov

clean:
	@rm -rf .venv
	@rm -f enterprise.db test_enterprise.db
	@rm -rf frontend/node_modules frontend/.next
	@rm -rf __pycache__ backend/__pycache__ tests/__pycache__
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
