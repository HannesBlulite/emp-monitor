#!/usr/bin/env python
"""Check last activity for all employees."""
import os
import sys
import django

# Load .env
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
if not os.path.exists(env_path):
    env_path = '/opt/emp-monitor/.env'
for line in open(env_path):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k] = v

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server'))
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ['DJANGO_SETTINGS_MODULE'] = 'empmonitor_server.settings'
django.setup()

from monitoring.models import Employee, ActivityLog, Screenshot
from django.utils import timezone

now = timezone.now()
print(f"Current UTC: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")

for emp in Employee.objects.all().order_by('display_name'):
    last_act = ActivityLog.objects.filter(employee=emp).order_by('-created_at').first()
    last_ss = Screenshot.objects.filter(employee=emp).order_by('-captured_at').first()
    last = None
    if last_act:
        last = last_act.created_at
    if last_ss and (not last or last_ss.captured_at > last):
        last = last_ss.captured_at
    if last:
        delta = now - last
        hours = delta.total_seconds() / 3600
        ago_str = f"{hours:.1f}h ago"
        status = "ALIVE" if hours < 0.5 else "STALE" if hours < 2 else "DEAD"
    else:
        ago_str = "never"
        status = "DEAD"
    print(f"[{status:5s}] {emp.display_name:20s} last={last}  ({ago_str})")
