#!/usr/bin/env python
"""Register agent package v1.2.2 and pull latest server code."""
import os, sys, django, shutil

for line in open('/opt/emp-monitor/.env'):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k] = v

os.environ['DJANGO_SETTINGS_MODULE'] = 'empmonitor_server.settings'
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server'))
django.setup()

from monitoring.models import AgentPackage
from django.core.files import File

# Deactivate old packages
AgentPackage.objects.filter(is_active=True).update(is_active=False)
print("Deactivated old packages")

# Copy ZIP to media location
src = '/opt/emp-monitor/empmonitor-agent-1.2.2.zip'
dest_dir = '/opt/emp-monitor/server/media/agent_packages'
os.makedirs(dest_dir, exist_ok=True)
dest = os.path.join(dest_dir, 'empmonitor-agent-1.2.2.zip')
shutil.copy2(src, dest)

# Create new package
pkg = AgentPackage.objects.create(
    version='1.2.2',
    is_active=True,
    notes='Fix toast notification: add reminder scenario with dismiss button, shorten message format',
)
pkg.package.name = 'agent_packages/empmonitor-agent-1.2.2.zip'
pkg.save()

print(f"Registered AgentPackage pk={pkg.pk}, version={pkg.version}, is_active={pkg.is_active}")
print(f"File: {pkg.package.name}")
