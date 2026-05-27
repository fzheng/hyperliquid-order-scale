.PHONY: run bot test install clean audit coverage

# Install dependencies
install:
	pip install -r requirements.txt

# Run the CLI tool
run:
	python -m cli.main

# Run the Telegram bot
bot:
	python -m bot.main

# Run all tests
test:
	python -m pytest tests/ -v

# Run dependency vulnerability audit
audit:
	pip-audit -r requirements.txt --strict

# Run tests with coverage report
coverage:
	pytest tests/ --cov --cov-report=term-missing

# Clean up cache files
clean:
	rm -rf __pycache__ .pytest_cache tests/__pycache__ core/__pycache__ cli/__pycache__ bot/__pycache__
