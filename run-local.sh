#!/usr/bin/env bash
# Doorman on this machine, no Databricks: SQLite data, simulated approvals, "Act as" switcher.
set -euo pipefail
cd "$(dirname "$0")"
export LOCAL_DB="${LOCAL_DB:-local/doorman.db}" DEV_USER="${DEV_USER:-younis@sierra.example}" GOVERNANCE=stub
exec streamlit run app.py --server.port "${PORT:-8501}" --server.headless true "$@"
