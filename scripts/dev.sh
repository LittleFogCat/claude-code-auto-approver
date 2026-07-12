#!/usr/bin/env bash
# Start the classifier service for development.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"
exec python -m uvicorn classifier.main:app --reload --host 127.0.0.1 --port 8765