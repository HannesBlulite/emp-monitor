#!/usr/bin/env bash
set -euo pipefail

cd /opt/emp-monitor/server
set -a
source /opt/emp-monitor/.env
set +a

/opt/emp-monitor/venv/bin/python - <<'PY'
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'empmonitor_server.settings')
django.setup()

from monitoring.models import Employee, AgentToken

# Create a test employee for Hannes's PC
emp, created = Employee.objects.get_or_create(
    employee_id='hannes-test',
    defaults={
        'display_name': 'Hannes (Test)',
        'department': 'Development',
        'pc_name': os.environ.get('COMPUTERNAME', 'DEV-PC'),
        'is_active': True,
    }
)
if created:
    print(f'Created employee: {emp}')
else:
    print(f'Employee exists: {emp}')

# Create agent token
token, t_created = AgentToken.objects.get_or_create(employee=emp)
if t_created:
    print(f'Created token: {token.token}')
else:
    print(f'Existing token: {token.token}')
PY
