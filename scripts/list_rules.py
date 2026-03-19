"""List all productivity rules for review."""
import django, os, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path('/opt/emp-monitor/.env'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'empmonitor_server.settings'
sys.path.insert(0, '/opt/emp-monitor/server')
django.setup()

from monitoring.models import ProductivityRule

rules = ProductivityRule.objects.all().order_by('match_type', 'pattern')
print(f'Total rules: {rules.count()}')
print(f'Apps: {rules.filter(match_type="app").count()}')
print(f'Domains: {rules.filter(match_type="domain").count()}')
print()

print('=== APP RULES ===')
for r in rules.filter(match_type='app'):
    print(f'  [{r.category}] {r.pattern}')

print()
print('=== DOMAIN RULES ===')
for r in rules.filter(match_type='domain'):
    print(f'  [{r.category}] {r.pattern}')
