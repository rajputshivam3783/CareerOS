#!/bin/sh
set -eu
if [ "${ENVIRONMENT:-development}" = "production" ]; then
  python -m scripts.run_migrations
fi
exec "$@"
