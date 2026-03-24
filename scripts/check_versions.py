import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'empmonitor_server.settings'
django.setup()
from monitoring.models import Employee
for e in Employee.objects.all().order_by('name'):
    print(f'{e.name}: v={e.agent_version}, seen={e.last_activity}')
