#!/usr/bin/env python
"""Check notification delivery status."""
import os, sys, django

for line in open('/opt/emp-monitor/.env'):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k] = v

os.environ['DJANGO_SETTINGS_MODULE'] = 'empmonitor_server.settings'
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server'))
django.setup()

from monitoring.models import Notification

print("Recent notifications:\n")
for n in Notification.objects.all().order_by('-created_at')[:12]:
    status = 'DELIVERED' if n.delivered_at else 'PENDING'
    created = n.created_at.strftime('%H:%M')
    delivered = n.delivered_at.strftime('%H:%M') if n.delivered_at else 'None'
    print(f"[{status:9s}] {n.employee.display_name:20s} created={created} delivered={delivered}  title={n.title[:40]}")
