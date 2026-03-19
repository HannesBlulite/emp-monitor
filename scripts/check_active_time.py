"""Diagnostic: check active_seconds vs window_log duration per employee today."""
import os, sys, django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'empmonitor_server.settings')
django.setup()

from monitoring.models import Employee, ActivityLog, AppUsageEntry
from django.utils import timezone
from django.db.models import Sum, Count, Min, Max

today = timezone.now().date()

for emp in Employee.objects.filter(is_active=True).order_by('display_name'):
    logs = emp.activity_logs.filter(created_at__date=today)
    count = logs.count()
    agg = logs.aggregate(
        total_active=Sum('active_seconds'),
        total_idle=Sum('idle_seconds'),
        first=Min('created_at'),
        last=Max('created_at'),
    )
    total_active = agg['total_active'] or 0
    total_idle = agg['total_idle'] or 0
    first = agg['first']
    last = agg['last']

    # Window log entries
    wl_entries = AppUsageEntry.objects.filter(
        activity_log__in=logs, timestamp__isnull=False
    )
    wl_dur = wl_entries.aggregate(t=Sum('duration_seconds'))['t'] or 0
    wl_count = wl_entries.count()

    # Check gap: total_active + total_idle vs wall clock
    if first and last:
        wall = (last - first).total_seconds()
    else:
        wall = 0

    print(f"\n{emp.display_name}:")
    print(f"  Logs: {count}, First: {first}, Last: {last}")
    print(f"  Wall clock span: {wall/3600:.1f}h")
    print(f"  active_seconds sum: {total_active:.0f}s = {total_active/3600:.1f}h")
    print(f"  idle_seconds sum:   {total_idle:.0f}s = {total_idle/3600:.1f}h")
    print(f"  active+idle total:  {(total_active+total_idle):.0f}s = {(total_active+total_idle)/3600:.1f}h")
    print(f"  window_log entries: {wl_count}, total dur: {wl_dur:.0f}s = {wl_dur/3600:.1f}h")
    if wall > 0:
        coverage = (total_active + total_idle) / wall * 100
        print(f"  Coverage (active+idle / wall): {coverage:.1f}%")
