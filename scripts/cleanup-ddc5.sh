#!/bin/bash
cd /opt/emp-monitor/server
source /opt/emp-monitor/venv/bin/activate
python manage.py shell -c "
from monitoring.models import Employee
emp = Employee.objects.get(employee_id='DDC5')
a = emp.activity_logs.all().count()
s = emp.screenshots.all().count()
emp.activity_logs.all().delete()
emp.screenshots.all().delete()
print(f'Deleted {a} activity logs and {s} screenshots for {emp.display_name}')
"
