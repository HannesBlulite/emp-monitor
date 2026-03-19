"""Check for double-counting in AppUsageEntry data."""
import django, os, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path('/opt/emp-monitor/.env'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'empmonitor_server.settings'
sys.path.insert(0, '/opt/emp-monitor/server')
django.setup()

from monitoring.models import Employee, AppUsageEntry
from django.db.models import Sum
from django.utils import timezone

danita = Employee.objects.get(display_name__icontains='danita')
today = timezone.now().date()
sched_logs = danita.activity_logs.filter(
    created_at__date=today,
    created_at__time__gte='07:00',
    created_at__time__lte='15:30',
)

entries = AppUsageEntry.objects.filter(activity_log__in=sched_logs)
print(f'Total AppUsageEntry rows: {entries.count()}')

wl = entries.filter(timestamp__isnull=False)
summary = entries.filter(timestamp__isnull=True)
print(f'Window_log entries (has timestamp): {wl.count()}')
print(f'Summary entries (no timestamp): {summary.count()}')
print()

# Summary entries breakdown
app_sum = summary.filter(domain='').aggregate(t=Sum('duration_seconds'))['t'] or 0
dom_sum = summary.exclude(domain='').aggregate(t=Sum('duration_seconds'))['t'] or 0
print(f'Summary app time (domain=empty): {app_sum:.0f}s = {app_sum/3600:.1f}h')
print(f'Summary domain time (domain set): {dom_sum:.0f}s = {dom_sum/3600:.1f}h')
print(f'Summary total: {app_sum + dom_sum:.0f}s = {(app_sum + dom_sum)/3600:.1f}h')
print()

# Window log breakdown
wl_app = wl.filter(domain='').aggregate(t=Sum('duration_seconds'))['t'] or 0
wl_dom = wl.exclude(domain='').aggregate(t=Sum('duration_seconds'))['t'] or 0
print(f'Window_log app time (no domain): {wl_app:.0f}s = {wl_app/3600:.1f}h')
print(f'Window_log domain time (has domain): {wl_dom:.0f}s = {wl_dom/3600:.1f}h')
print(f'Window_log total: {wl_app + wl_dom:.0f}s = {(wl_app + wl_dom)/3600:.1f}h')
print()

# Active seconds for comparison
active = sched_logs.aggregate(t=Sum('active_seconds'))['t'] or 0
print(f'Active seconds from logs: {active:.0f}s = {active/3600:.1f}h')
print()

# Grand total (what _classify_usage currently sums)
all_app = entries.filter(domain='').values('process_name').annotate(t=Sum('duration_seconds'))
all_dom = entries.exclude(domain='').values('domain').annotate(t=Sum('duration_seconds'))
total_app = sum(e['t'] for e in all_app if e['process_name'] != '[website]')
total_dom = sum(e['t'] for e in all_dom)
print(f'Current _classify_usage app total: {total_app:.0f}s = {total_app/3600:.1f}h')
print(f'Current _classify_usage domain total: {total_dom:.0f}s = {total_dom/3600:.1f}h')
print(f'Current grand total (inflated): {total_app + total_dom:.0f}s = {(total_app + total_dom)/3600:.1f}h')
