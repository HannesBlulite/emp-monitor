#!/usr/bin/env python
"""Count today's activity logs per employee to check for multi-reporting."""
import os, sys

# Load .env (same approach as check_recent.py)
env_path = '/opt/emp-monitor/.env'
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, val = line.split('=', 1)
            os.environ.setdefault(key.strip(), val.strip())

os.environ['DJANGO_SETTINGS_MODULE'] = 'empmonitor_server.settings'
sys.path.insert(0, '/opt/emp-monitor/server')
import django
django.setup()

from monitoring.models import Employee, ActivityLog
from django.utils import timezone
from django.db.models import Sum

today = timezone.now().date()
print(f"Date: {today}")
print("-" * 60)

for emp in Employee.objects.filter(is_active=True).order_by('display_name'):
    qs = emp.activity_logs.filter(created_at__date=today)
    count = qs.count()
    total_active = int(qs.aggregate(t=Sum('active_seconds'))['t'] or 0)
    hours = total_active // 3600
    mins = (total_active % 3600) // 60
    secs = total_active % 60
    print(f"{emp.display_name:20s}  logs={count:5d}  active={hours:02d}:{mins:02d}:{secs:02d}")
