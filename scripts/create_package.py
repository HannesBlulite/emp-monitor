import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'empmonitor_server.settings'
django.setup()

from monitoring.models import AgentPackage

# Deactivate all existing packages
AgentPackage.objects.filter(is_active=True).update(is_active=False)
print("Deactivated old packages")

# Create v1.3.0
pkg = AgentPackage.objects.create(
    version='1.3.0',
    package='agent_packages/empmonitor-agent-1.3.0.zip',
    notes='Fix BOM issue in config.json loading (utf-8-sig encoding), add token debug logging',
    is_active=True,
)
print(f"Created: {pkg}")
print(f"Active packages: {list(AgentPackage.objects.filter(is_active=True).values_list('version', flat=True))}")
