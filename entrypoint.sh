#!/bin/bash
set -e

# Run DB migrations and hub initialization
poetry run python -m node.storage.db.init_db | tee /dev/stdout
poetry run python -m node.storage.hub.init_hub | tee /dev/stdout
poetry run python -m node.storage.hub.init_hub --user | tee /dev/stdout

# Start celery worker detached
nohup poetry run celery -A node.worker.main:app worker --loglevel=info > /dev/stdout 2>&1 &

# Start WS server detached
nohup poetry run python -m node.server.server --communication-protocol ws --port 7002 > /dev/stdout 2>&1 &

# Run HTTP server as the main foreground process so it receives SIGTERM
exec poetry run python -m node.server.server --communication-protocol http --port 7001