.PHONY: run bot test install clean

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

# Clean up cache files
clean:
	rm -rf __pycache__ .pytest_cache tests/__pycache__ core/__pycache__ cli/__pycache__ bot/__pycache__
