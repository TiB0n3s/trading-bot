#!/usr/bin/env python3
"""Explicit WSGI entrypoint for production startup.

Importing app.py is side-effect-light for tests. Importing this module is the
production boot path: it creates the Flask app and runs startup hooks once.
"""

from app import create_app


application = create_app(run_startup=True)
