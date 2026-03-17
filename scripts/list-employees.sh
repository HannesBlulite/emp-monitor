#!/bin/bash
cd /opt/emp-monitor/server
source /opt/emp-monitor/venv/bin/activate
python manage.py shell -c "
from monitoring.models import Employee, ActivityLog, Screenshot, AppUsageEntry
for e in Employee.objects.all():
    a = e.activity_logs.count()
    s = e.screenshots.count()
    print(f'{e.employee_id} | {e.display_name} | {a} logs | {s} screenshots')
"
