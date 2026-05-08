"""Set display_order for employees (run AFTER migrating on production)."""
import os, sys

# Load .env
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
if not os.path.exists(env_path):
    env_path = '/opt/emp-monitor/.env'
if os.path.exists(env_path):
    for line in open(env_path):
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ[k] = v

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'empmonitor_server.settings')

import django
django.setup()

from monitoring.models import Employee

# Desired order: display_name fragment → display_order
ORDER = [
    ('Nicole',   1),
    ('Danita',   2),
    ('Lizelle',  3),
    ('Janelda',  4),
    ('Monique',  5),
    ('Jeandri',  6),
    ('Stephan',  7),
]

for name_fragment, order in ORDER:
    qs = Employee.objects.filter(display_name__icontains=name_fragment)
    if qs.count() == 1:
        emp = qs.first()
        emp.display_order = order
        emp.save(update_fields=['display_order'])
        print(f"  [{order}] {emp.display_name} — OK")
    elif qs.count() == 0:
        print(f"  [{order}] WARNING: No employee found matching '{name_fragment}'")
    else:
        print(f"  [{order}] WARNING: Multiple employees match '{name_fragment}': {[e.display_name for e in qs]}")

print("\nFinal order:")
for emp in Employee.objects.all():
    print(f"  {emp.display_order:2d}  {emp.display_name}")
