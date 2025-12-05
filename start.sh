#!/bin/bash
# CryptoLens Production Start Script

set -e

# Configuration
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${APP_DIR}/venv"
LOG_LEVEL="${LOG_LEVEL:-info}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting CryptoLens...${NC}"

# Check virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${RED}Error: Virtual environment not found at ${VENV_DIR}${NC}"
    echo "Run: python -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Activate virtual environment
source "${VENV_DIR}/bin/activate"

# Ensure data directory exists
mkdir -p "${APP_DIR}/data"

# Check if already running
if pgrep -f "gunicorn.*cryptolens" > /dev/null; then
    echo -e "${YELLOW}Warning: CryptoLens appears to be already running${NC}"
    echo "Use: pkill -f 'gunicorn.*cryptolens' to stop it first"
    exit 1
fi

# Set environment
export FLASK_ENV="${FLASK_ENV:-production}"
export LOG_LEVEL="${LOG_LEVEL}"

# Start with gunicorn
echo -e "${GREEN}Starting Gunicorn with config: gunicorn.conf.py${NC}"
echo "Environment: FLASK_ENV=${FLASK_ENV}, LOG_LEVEL=${LOG_LEVEL}"

exec gunicorn -c gunicorn.conf.py "app:create_app()"
