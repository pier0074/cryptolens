#!/usr/bin/env python3
"""
CryptoLens - Smart Money Pattern Detection System
Entry point for the Flask application
"""
import os
import socket
from app import create_app, db
from app.models import Symbol
from app.config import Config

app = create_app()


def init_symbols():
    """Initialize default symbols in database"""
    with app.app_context():
        for symbol_name in Config.SYMBOLS:
            existing = Symbol.query.filter_by(symbol=symbol_name).first()
            if not existing:
                symbol = Symbol(symbol=symbol_name, exchange='kucoin')
                db.session.add(symbol)
        db.session.commit()
        print(f"Initialized {len(Config.SYMBOLS)} symbols")


def is_port_available(port):
    """Check if a port is available"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('0.0.0.0', port))
            return True
        except OSError:
            return False


def find_available_port(start_port=5000, max_attempts=10):
    """Find an available port starting from start_port"""
    for i in range(max_attempts):
        port = start_port + i
        if is_port_available(port):
            return port
    return start_port + max_attempts


if __name__ == '__main__':
    # Initialize symbols on first run (only in main process)
    is_reloader = os.getenv('WERKZEUG_RUN_MAIN') == 'true'

    if not is_reloader:
        init_symbols()

    # Get port - check if already set by parent process (for reloader)
    debug = os.getenv('FLASK_ENV', 'development') == 'development'

    if os.getenv('CRYPTOLENS_PORT'):
        # Reloader child process - use the port set by parent
        port = int(os.getenv('CRYPTOLENS_PORT'))
    else:
        # Main process - find available port
        preferred_port = int(os.getenv('PORT', 5000))

        if is_port_available(preferred_port):
            port = preferred_port
        else:
            port = find_available_port(preferred_port)
            print(f"Port {preferred_port} in use, using port {port} instead")

        # Set for reloader child process
        os.environ['CRYPTOLENS_PORT'] = str(port)

    if not is_reloader:
        print(f"""
    ╔═══════════════════════════════════════════════════╗
    ║           CryptoLens - Pattern Detector           ║
    ║        Smart Money Pattern Detection System       ║
    ╠═══════════════════════════════════════════════════╣
    ║  Dashboard:  http://localhost:{port}                 ║
    ║  API:        http://localhost:{port}/api             ║
    ╚═══════════════════════════════════════════════════╝
        """)

    app.run(host='0.0.0.0', port=port, debug=debug)
