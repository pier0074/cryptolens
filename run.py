#!/usr/bin/env python3
"""
CryptoLens - Smart Money Pattern Detection System
Entry point for the Flask application
"""
import os
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


if __name__ == '__main__':
    # Initialize symbols on first run
    init_symbols()

    # Run the app
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV', 'development') == 'development'

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
