# -*- coding: utf-8 -*-
"""
Combined Entry Point: Runs both TrustVote Election System and First-Time Voter Portal
under a single web server instance for 1-service cloud hosting (e.g. Render Free Tier).
- /          -> TrustVote Election System (Admin, Booth Officer, Scanner, Blockchain)
- /portal    -> First-Time Voter e-EPIC Download Portal & Form No. 6
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from werkzeug.middleware.dispatcher import DispatcherMiddleware
from app import app as trustvote_app
from voter_portal_app import app as voter_portal_app

# Mount voter portal at /portal while main election system runs at root /
application = DispatcherMiddleware(trustvote_app, {
    '/portal': voter_portal_app
})

app = application

if __name__ == '__main__':
    from werkzeug.serving import run_simple
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Unified TrustVote Platform on port {port}...")
    print(f"  - TrustVote System: http://127.0.0.1:{port}/")
    print(f"  - Voter Portal:     http://127.0.0.1:{port}/portal")
    run_simple('0.0.0.0', port, application, use_reloader=False)
