#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

echo "================================================="
echo "ENCERRANDO PORT-FORWARDS"
echo "================================================="

for name in \
  grafana \
  prometheus \
  loki \
  jobs-api \
  argocd; do

  stop_saved_port_forward "${name}"
  echo "OK: ${name}"
done

echo "================================================="