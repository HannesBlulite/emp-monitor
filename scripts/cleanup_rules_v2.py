"""Clean up junk rules, fix misclassified, and set remaining neutral to productive."""
import django, os, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path('/opt/emp-monitor/.env'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'empmonitor_server.settings'
sys.path.insert(0, '/opt/emp-monitor/server')
django.setup()

from monitoring.models import ProductivityRule

# === 1. DELETE JUNK ENTRIES ===
junk_patterns = [
    ('domain', 'steenkamp.op@gmail.com'),
    ('domain', 'marieoni.vschalkwyk@partner4life.co.za'),
    ('domain', 'tsuifuiwa.muvhango@'),
    ('domain', 'shellapp.namespace(zipfilepath).copyhere'),
    ('domain', 'zte_1d5851_2.4g'),
    ('domain', 's61.80|v43.52'),
    ('domain', 'storelogs.dev.empmonitor.com'),
]
# Corrupted app names
junk_app_patterns_contains = [
    '\u2500', '\u0446', '\u00b5', '\u00e1', '\u00c1',  # corrupted chars
]

deleted = 0
for match_type, pattern in junk_patterns:
    count = ProductivityRule.objects.filter(match_type=match_type, pattern=pattern).count()
    if count:
        ProductivityRule.objects.filter(match_type=match_type, pattern=pattern).delete()
        deleted += count
        print(f'  DELETED [{match_type}] {pattern}')

# Delete corrupted app names
for rule in ProductivityRule.objects.filter(match_type='app'):
    if any(c in rule.pattern for c in junk_app_patterns_contains):
        print(f'  DELETED [app] {repr(rule.pattern)}')
        rule.delete()
        deleted += 1

print(f'\nTotal junk deleted: {deleted}')

# === 2. FIX MISCLASSIFIED: productive -> unproductive ===
to_unproductive = [
    ('domain', 'utorrent.com'),
    ('domain', 'massgrave.dev'),
    ('domain', 'telegram.download-program.ru'),
    ('domain', 'msn.com'),
    ('domain', 'wa.me'),
    ('app', 'utorrent web'),
    ('app', 'kmspico (2021) 11.2.4'),
    ('app', 'kms gui eldi'),
    ('app', 'game bar'),
]
# SendGrid tracking pixel domains
sendgrid_rules = ProductivityRule.objects.filter(
    match_type='domain', pattern__endswith='.ct.sendgrid.net'
)

reclassified = 0
for match_type, pattern in to_unproductive:
    count = ProductivityRule.objects.filter(
        match_type=match_type, pattern=pattern
    ).exclude(category='unproductive').update(category='unproductive')
    if count:
        reclassified += count
        print(f'  -> unproductive [{match_type}] {pattern}')

sg_count = sendgrid_rules.exclude(category='unproductive').update(category='unproductive')
if sg_count:
    reclassified += sg_count
    print(f'  -> unproductive [domain] *.ct.sendgrid.net ({sg_count} rules)')

# === 3. FIX MISCLASSIFIED: unproductive -> productive ===
to_productive = [
    ('domain', 'w3schools.com'),
    ('domain', 'support.hp.com'),
    ('domain', 'support.lenovo.com'),
    ('domain', 'support.amd.com'),
    ('domain', 'tools.sars.gov.za'),
    ('domain', 'vertex42.com'),
]
for match_type, pattern in to_productive:
    count = ProductivityRule.objects.filter(
        match_type=match_type, pattern=pattern
    ).exclude(category='productive').update(category='productive')
    if count:
        reclassified += count
        print(f'  -> productive [{match_type}] {pattern}')

print(f'\nTotal reclassified: {reclassified}')

# === 4. SET ALL REMAINING NEUTRAL TO PRODUCTIVE ===
remaining_neutral = ProductivityRule.objects.filter(category='neutral')
neutral_count = remaining_neutral.count()
if neutral_count:
    remaining_neutral.update(category='productive')
    print(f'\nSet {neutral_count} neutral rules to productive')
else:
    print(f'\nNo neutral rules remaining')

# === SUMMARY ===
print(f'\n=== FINAL COUNTS ===')
for cat in ['productive', 'unproductive', 'neutral']:
    c = ProductivityRule.objects.filter(category=cat).count()
    print(f'  {cat}: {c}')
print(f'  TOTAL: {ProductivityRule.objects.count()}')
