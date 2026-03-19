#!/usr/bin/env python
"""Count and optionally delete junk ProductivityRules (PDFs, GUIDs, etc.)."""
import os, sys, re

env_path = '/opt/emp-monitor/.env'
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, val = line.split('=', 1)
            os.environ.setdefault(key.strip(), val.strip())

os.environ['DJANGO_SETTINGS_MODULE'] = 'empmonitor_server.settings'
sys.path.insert(0, '/opt/emp-monitor/server')
import django
django.setup()

from monitoring.models import ProductivityRule

# Patterns that indicate junk domain entries
junk_patterns = [
    re.compile(r'\.pdf$', re.IGNORECASE),           # PDF filenames
    re.compile(r'\.docx?$', re.IGNORECASE),          # Word docs
    re.compile(r'\.xlsx?$', re.IGNORECASE),          # Excel files
    re.compile(r'\.pptx?$', re.IGNORECASE),          # PowerPoint
    re.compile(r'\.txt$', re.IGNORECASE),            # Text files
    re.compile(r'\.csv$', re.IGNORECASE),            # CSV files
    re.compile(r'\.png$', re.IGNORECASE),            # Images
    re.compile(r'\.jpg$', re.IGNORECASE),
    re.compile(r'\.jpeg$', re.IGNORECASE),
    re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-', re.IGNORECASE),  # GUIDs
    re.compile(r'^https?://', re.IGNORECASE),        # Full URLs (should be just domain)
    re.compile(r'\\'),                               # Backslash paths
    re.compile(r'^[\d.]+$'),                         # Just numbers/dots (not real domains)
]

domain_rules = ProductivityRule.objects.filter(match_type='domain')
junk_ids = []
for rule in domain_rules:
    for pat in junk_patterns:
        if pat.search(rule.pattern):
            junk_ids.append(rule.id)
            break

print(f"Total domain rules: {domain_rules.count()}")
print(f"Junk rules found: {len(junk_ids)}")

if junk_ids:
    # Show some examples
    examples = ProductivityRule.objects.filter(id__in=junk_ids[:20])
    print("\nExamples:")
    for r in examples:
        print(f"  {r.pattern}")

    if '--delete' in sys.argv:
        deleted = ProductivityRule.objects.filter(id__in=junk_ids).delete()
        print(f"\nDeleted {deleted[0]} junk rules")
    else:
        print("\nRun with --delete to actually remove them")
