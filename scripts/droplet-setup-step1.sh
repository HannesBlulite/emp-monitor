#!/usr/bin/env bash
set -euo pipefail

# Fix .env encoding (strip BOM + CRLF)
python3 - <<'PY'
from pathlib import Path
p = Path('/opt/emp-monitor/.env')
raw = p.read_bytes()
if raw[:3] == b'\xef\xbb\xbf':
    raw = raw[3:]
raw = raw.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
p.write_bytes(raw)
print('.env cleaned')
PY

# Also fix any CRLF in manage.py or settings just in case
find /opt/emp-monitor/server -name '*.py' -exec sed -i 's/\r$//' {} +

cd /opt/emp-monitor/server
set -a
source /opt/emp-monitor/.env
set +a

echo "--- Django check ---"
/opt/emp-monitor/venv/bin/python manage.py check

echo "--- Django check passed ---"
