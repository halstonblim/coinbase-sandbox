#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  echo "Missing $SCRIPT_DIR/.env" >&2
  exit 1
fi

if [[ ! -f "$SCRIPT_DIR/list_products.py" ]]; then
  echo "Missing $SCRIPT_DIR/list_products.py" >&2
  exit 1
fi

set -a
source "$SCRIPT_DIR/.env"
set +a

exec python "$SCRIPT_DIR/list_products.py"
