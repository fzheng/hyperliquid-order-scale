.PHONY: run test install clean

# Install dependencies
install:
	pip install -r requirements.txt

# Run the CLI tool
run:
	python scale_orders.py

# Run all tests
test:
	python -m pytest tests/ -v

# Clean up cache files
clean:
	rm -rf __pycache__ .pytest_cache tests/__pycache__
