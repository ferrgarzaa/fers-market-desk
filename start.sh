#!/usr/bin/env bash
# Starts backend (FastAPI on :8000) and frontend (Vite on :5173). Mac / Linux.
set -e
cd "$(dirname "$0")"
if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -r backend/requirements-dev.txt
fi
[ -d frontend/node_modules ] || (cd frontend && npm install)
(cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000) &
BACK=$!
trap "kill $BACK" EXIT
cd frontend && npm run dev
