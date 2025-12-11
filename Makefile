.PHONY: help install dev db-create db-drop db-reset db-init db-shell db-migrate-sqlite test test-fast run

help:
	@echo "CryptoLens Development Commands"
	@echo ""
	@echo "Quick Start:"
	@echo "  make install     - Install Python dependencies"
	@echo "  make db-create   - Create MySQL database"
	@echo "  make db-init     - Initialize database tables"
	@echo "  make dev         - Start development server"
	@echo ""
	@echo "Database:"
	@echo "  make db-shell    - Open MySQL shell"
	@echo "  make db-drop     - Drop database (WARNING: deletes data)"
	@echo "  make db-reset    - Drop and recreate database"
	@echo "  make db-migrate-sqlite - Migrate from SQLite to MySQL"
	@echo ""
	@echo "Development:"
	@echo "  make test        - Run test suite"
	@echo "  make test-fast   - Run tests (stop on first failure)"
	@echo "  make run         - Run with gunicorn (production-like)"

install:
	pip install -r requirements.txt

db-create:
	@echo "Creating MySQL database 'cryptolens'..."
	@mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS cryptolens CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
	@echo "Database created successfully!"

db-drop:
	@echo "WARNING: This will delete the database!"
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ]
	mysql -u root -p -e "DROP DATABASE IF EXISTS cryptolens;"
	@echo "Database dropped."

db-reset: db-drop db-create db-init

db-init:
	python scripts/init_db.py

db-shell:
	mysql -u root -p cryptolens

db-migrate-sqlite:
	@echo "This will migrate data from SQLite to MySQL"
	@echo "Make sure MySQL database exists (make db-create)"
	@echo ""
	python scripts/init_db.py --migrate data/cryptolens.db

dev:
	flask run --debug

test:
	python -m pytest tests/ -v

test-fast:
	python -m pytest tests/ -v -x

run:
	gunicorn -w 4 -b 0.0.0.0:5000 "app:create_app()"
