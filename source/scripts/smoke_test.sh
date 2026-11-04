#!/usr/bin/env bash
set -euo pipefail
# No credentials are printed. Run against the exposed server.
base_url="${1:-http://localhost:8080}"
curl --fail --silent --show-error "$base_url/healthz"
curl --fail --silent --show-error "$base_url/readyz"
status_code=$(curl --silent --output /dev/null --write-out '%{http_code}' "$base_url/api/data")
if [ "$status_code" != "401" ]; then
  echo "Expected unauthenticated API status 401; got $status_code" >&2
  exit 1
fi
echo 'Health/readiness OK; unauthenticated API is protected.'
