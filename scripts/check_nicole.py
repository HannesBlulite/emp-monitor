"""Quick check of Nicole's agent data on the server."""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'empmonitor_server.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
django.setup()

from monitoring.models import Employee, ActivityLog, ScreenshotEntry
from django.utils import timezone

nicole = Employee.objects.filter(name__icontains='nicole').first()
if not nicole:
    print("Nicole not found!")
    sys.exit(1)

print(f"Employee: {nicole.name} (ID={nicole.id})")
print(f"Agent token: {nicole.agent_token[:8]}...")
print(f"Last seen: {nicole.last_seen}")
print()

logs = ActivityLog.objects.filter(employee=nicole).order_by('-timestamp')[:10]
print(f"Recent activity logs ({logs.count()}):")
for l in logs:
    app = l.active_app_name[:50] if l.active_app_name else "None"
    print(f"  {l.timestamp} | active={l.is_active} | app={app}")
print()

shots = ScreenshotEntry.objects.filter(employee=nicole).order_by('-captured_at')[:5]
print(f"Recent screenshots ({shots.count()}):")
for s in shots:
    print(f"  {s.captured_at} | {s.image_file}")
