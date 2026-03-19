#!/usr/bin/env python
"""Remove duplicate ActivityLogs for Monique Louw on 2026-03-19.
Keeps only the first log per ~30s window, deletes the rest."""
import os, sys

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

from monitoring.models import Employee, ActivityLog, AppUsageEntry
from django.utils import timezone
from datetime import date, timedelta

emp = Employee.objects.get(display_name='MONIQUE LOUW')
today = date(2026, 3, 19)
logs = ActivityLog.objects.filter(
    employee=emp, created_at__date=today
).order_by('created_at')

total = logs.count()
print(f"Total logs for {emp.display_name} on {today}: {total}")

# Walk through logs, keep first in each 30s window, mark rest for deletion
keep_ids = []
delete_ids = []
last_kept_time = None

for log in logs:
    if last_kept_time is None or (log.created_at - last_kept_time).total_seconds() >= 30:
        keep_ids.append(log.id)
        last_kept_time = log.created_at
    else:
        delete_ids.append(log.id)

print(f"Keeping: {len(keep_ids)}")
print(f"Deleting: {len(delete_ids)}")

if delete_ids:
    # Delete associated AppUsageEntries first, then the logs
    usage_deleted = AppUsageEntry.objects.filter(activity_log_id__in=delete_ids).delete()
    log_deleted = ActivityLog.objects.filter(id__in=delete_ids).delete()
    print(f"Deleted {usage_deleted[0]} AppUsageEntries and {log_deleted[0]} ActivityLogs")
else:
    print("Nothing to delete")
