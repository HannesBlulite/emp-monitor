"""Identify which employees are behind each IP that downloaded v1.2.0."""
import os, sys, django

env_path = '/opt/emp-monitor/.env'
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, _, val = line.partition('=')
            os.environ.setdefault(key.strip(), val.strip())

sys.path.insert(0, '/opt/emp-monitor/server')
os.environ['DJANGO_SETTINGS_MODULE'] = 'empmonitor_server.settings'
os.chdir('/opt/emp-monitor/server')
django.setup()

from monitoring.models import Employee, ActivityLog
from django.utils import timezone
from datetime import timedelta

today = timezone.now().date()

# IPs that downloaded v1.2.0 (from nginx logs)
bricked_ips = ['192.143.227.0', '41.133.98.191', '196.210.53.59', '102.32.169.78', '102.220.210.76']

print("=== All employees and their last activity ===\n")
for emp in Employee.objects.filter(is_active=True):
    last = emp.activity_logs.order_by('-created_at').first()
    if last:
        gap = timezone.now() - last.created_at
        hours = gap.total_seconds() / 3600
        status = "LIKELY BRICKED" if hours > 1.5 else "ACTIVE"
        print(f"  {emp.display_name:20s}  last seen: {last.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}  ({hours:.1f}h ago)  [{status}]")
    else:
        print(f"  {emp.display_name:20s}  last seen: never")
