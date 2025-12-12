.PHONY: help install dev db-create db-drop db-reset db-init db-shell db-migrate-sqlite test test-fast run

help:
	@echo "CryptoLens Development Commands"
	@echo ""
	@echo "Quick Start:"
	@echo "  make install     - Install Python dependencies"
	@echo "  make db-create   - Create MySQL database (uses .env credentials)"
	@echo "  make dev         - Start development server"
	@echo ""
	@echo "Database:"
	@echo "  make db-init     - Initialize tables only (db must exist)"
	@echo "  make db-drop     - Drop database (WARNING: deletes data)"
	@echo "  make db-reset    - Drop and recreate database"
	@echo "  make db-shell    - Open MySQL shell"
	@echo "  make db-migrate-sqlite - Migrate from SQLite to MySQL"
	@echo ""
	@echo "Development:"
	@echo "  make test        - Run test suite"
	@echo "  make test-fast   - Run tests (stop on first failure)"
	@echo "  make run         - Run with gunicorn (production-like)"

install:
	pip install -r requirements.txt

db-create:
	python scripts/init_db.py --create

db-drop:
	python scripts/init_db.py --drop

db-reset:
	python scripts/init_db.py --drop
	python scripts/init_db.py --create

db-init:
	python scripts/init_db.py

db-shell:
	@python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(f\"mysql -h {os.getenv('DB_HOST', 'localhost')} -P {os.getenv('DB_PORT', '3306')} -u {os.getenv('DB_USER', 'root')} -p {os.getenv('DB_NAME', 'cryptolens')}\")"
	@python -c "from dotenv import load_dotenv; import os; load_dotenv(); os.system(f\"mysql -h {os.getenv('DB_HOST', 'localhost')} -P {os.getenv('DB_PORT', '3306')} -u {os.getenv('DB_USER', 'root')} -p{os.getenv('DB_PASS', '')} {os.getenv('DB_NAME', 'cryptolens')}\")"

db-migrate-sqlite:
	python scripts/init_db.py --migrate data/cryptolens.db

dev:
	flask run --debug

test:
	python -m pytest tests/ -v

test-fast:
	python -m pytest tests/ -v -x

run:
	gunicorn -w 4 -b 0.0.0.0:5000 "app:create_app()"
