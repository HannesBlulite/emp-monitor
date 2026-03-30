"""
Management command: send_daily_timesheet_email

Sends each employee (who has an email address) an email with their
timesheet data for a given date.  Defaults to today.

Intended to be run nightly at 20:00 via a systemd timer or cron job:
    python manage.py send_daily_timesheet_email
    python manage.py send_daily_timesheet_email --date 2026-03-19
"""

import zoneinfo
from datetime import date as date_type, time as time_type, timedelta

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db.models import Sum, Min, Max, Q
from django.template.loader import render_to_string
from django.utils import timezone

from monitoring.models import (
    Employee, ActivityLog, AppUsageEntry, ProductivityRule,
    ClockTimeOverride,
)

LOCAL_TZ = zoneinfo.ZoneInfo('Africa/Johannesburg')
SCHEDULE_START = time_type(7, 0)
SCHEDULE_END = time_type(15, 30)


def _time_to_secs(t):
    return t.hour * 3600 + t.minute * 60 + t.second


SCHED_START_S = _time_to_secs(SCHEDULE_START)
SCHED_END_S = _time_to_secs(SCHEDULE_END)


def _fmt_duration(seconds):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _match_domain_rule(domain, domain_rules):
    domain = domain.lower()
    if domain in domain_rules:
        return domain_rules[domain]
    for pattern, category in domain_rules.items():
        if domain.endswith('.' + pattern):
            return category
    return 'neutral'


def _classify_usage(usage_qs, app_rules, domain_rules):
    productive = 0
    unproductive = 0
    neutral = 0
    wl = usage_qs.filter(timestamp__isnull=False)
    for entry in wl.exclude(domain='').values('domain').annotate(total=Sum('duration_seconds')):
        cat = _match_domain_rule(entry['domain'], domain_rules)
        dur = entry['total']
        if cat == 'productive':
            productive += dur
        elif cat == 'unproductive':
            unproductive += dur
        else:
            neutral += dur
    for entry in wl.filter(domain='').values('process_name').annotate(total=Sum('duration_seconds')):
        name = entry['process_name']
        if name in ('[website]', 'unknown'):
            continue
        app_key = name.lower().replace('.exe', '')
        cat = app_rules.get(app_key, app_rules.get(name.lower(), 'neutral'))
        dur = entry['total']
        if cat == 'productive':
            productive += dur
        elif cat == 'unproductive':
            unproductive += dur
        else:
            neutral += dur
    return productive, unproductive, neutral


def build_timesheet_row(emp, target_date, app_rules, domain_rules):
    """Build a single timesheet row dict for an employee on a date."""
    logs = emp.activity_logs.filter(created_at__date=target_date)
    if not logs.exists():
        return None

    times = logs.aggregate(clock_in=Min('created_at'), clock_out=Max('created_at'))
    clock_in = times['clock_in']
    clock_out = times['clock_out']

    ci_local = timezone.localtime(clock_in, LOCAL_TZ)
    co_local = timezone.localtime(clock_out, LOCAL_TZ)

    # Apply clock-time overrides if present
    try:
        override = ClockTimeOverride.objects.get(employee=emp, date=target_date)
        if override.clock_in_override:
            ci_local = ci_local.replace(
                hour=override.clock_in_override.hour,
                minute=override.clock_in_override.minute,
                second=override.clock_in_override.second,
            )
            clock_in = ci_local
        if override.clock_out_override:
            co_local = co_local.replace(
                hour=override.clock_out_override.hour,
                minute=override.clock_out_override.minute,
                second=override.clock_out_override.second,
            )
            clock_out = co_local
    except ClockTimeOverride.DoesNotExist:
        pass

    ci_s = _time_to_secs(ci_local.time())
    co_s = _time_to_secs(co_local.time())

    early_ot_secs = max(0, min(co_s, SCHED_START_S) - ci_s) if ci_s < SCHED_START_S else 0
    late_ot_secs = max(0, co_s - max(ci_s, SCHED_END_S)) if co_s > SCHED_END_S else 0
    total_ot_secs = early_ot_secs + late_ot_secs

    sched_logs = logs.filter(
        created_at__time__gte=SCHEDULE_START,
        created_at__time__lte=SCHEDULE_END,
    )
    ot_logs = logs.filter(
        Q(created_at__time__lt=SCHEDULE_START) |
        Q(created_at__time__gt=SCHEDULE_END)
    )

    all_agg = logs.aggregate(a=Sum('active_seconds'), i=Sum('idle_seconds'))
    total_active = (all_agg['a'] or 0) + (all_agg['i'] or 0)

    sched_agg = sched_logs.aggregate(a=Sum('active_seconds'), i=Sum('idle_seconds'))
    sched_active = (sched_agg['a'] or 0) + (sched_agg['i'] or 0)

    sched_usage = AppUsageEntry.objects.filter(activity_log__in=sched_logs)
    sched_productive, _, _ = _classify_usage(sched_usage, app_rules, domain_rules)

    ot_usage = AppUsageEntry.objects.filter(activity_log__in=ot_logs)
    ot_productive, _, _ = _classify_usage(ot_usage, app_rules, domain_rules)

    ot_agg = ot_logs.aggregate(a=Sum('active_seconds'), i=Sum('idle_seconds'))
    ot_active = (ot_agg['a'] or 0) + (ot_agg['i'] or 0)

    sched_prod_pct = round(sched_productive / sched_active * 100, 1) if sched_active > 0 else 0
    ot_prod_pct = round(ot_productive / ot_active * 100, 1) if ot_active > 0 else 0

    ci_time_sast = ci_local.time()
    if ci_time_sast <= SCHEDULE_START:
        status = 'on_time'
    elif ci_time_sast <= time_type(7, 15):
        status = 'late'
    else:
        status = 'very_late'

    return {
        'status': status,
        'clock_in': clock_in,
        'clock_out': clock_out,
        'total_active': _fmt_duration(total_active),
        'sched_active': _fmt_duration(sched_active),
        'sched_prod_pct': sched_prod_pct,
        'total_ot': _fmt_duration(total_ot_secs),
        'ot_prod_pct': ot_prod_pct,
    }


class Command(BaseCommand):
    help = 'Send each employee a daily timesheet email for a given date.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default='',
            help='Date in YYYY-MM-DD format. Defaults to today (SAST).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be sent without actually sending emails.',
        )

    def handle(self, *args, **options):
        if options['date']:
            target_date = date_type.fromisoformat(options['date'])
        else:
            target_date = timezone.localtime(timezone.now(), LOCAL_TZ).date()

        dry_run = options['dry_run']

        app_rules = {
            r.pattern.lower(): r.category
            for r in ProductivityRule.objects.filter(match_type='app')
        }
        domain_rules = {
            r.pattern.lower(): r.category
            for r in ProductivityRule.objects.filter(match_type='domain')
        }

        employees = Employee.objects.filter(is_active=True).exclude(email='')
        sent = 0
        skipped = 0

        for emp in employees:
            row = build_timesheet_row(emp, target_date, app_rules, domain_rules)

            context = {
                'employee': emp,
                'date': target_date,
                'row': row,
            }

            subject = f"Timesheet: {emp.display_name} — {target_date.strftime('%A %d %B %Y')}"
            html_body = render_to_string('monitoring/email_daily_timesheet.html', context)
            # Plain-text fallback
            if row:
                plain = (
                    f"Daily Timesheet — {emp.display_name}\n"
                    f"Date: {target_date}\n"
                    f"Status: {row['status']}\n"
                    f"Clock In: {row['clock_in'].strftime('%H:%M')}\n"
                    f"Clock Out: {row['clock_out'].strftime('%H:%M')}\n"
                    f"Total Active: {row['total_active']}\n"
                    f"Scheduled Productivity: {row['sched_prod_pct']}%\n"
                    f"Overtime: {row['total_ot']}\n"
                )
            else:
                plain = (
                    f"Daily Timesheet — {emp.display_name}\n"
                    f"Date: {target_date}\n"
                    f"No activity recorded.\n"
                )

            if dry_run:
                self.stdout.write(
                    self.style.SUCCESS(f"[DRY RUN] Would send to {emp.email}: {subject}")
                )
                if row:
                    self.stdout.write(f"  Clock In: {row['clock_in'].strftime('%H:%M')}  "
                                      f"Clock Out: {row['clock_out'].strftime('%H:%M')}  "
                                      f"Active: {row['total_active']}  "
                                      f"Prod: {row['sched_prod_pct']}%")
                else:
                    self.stdout.write("  No activity data.")
                sent += 1
                continue

            try:
                send_mail(
                    subject=subject,
                    message=plain,
                    from_email=None,  # Uses DEFAULT_FROM_EMAIL
                    recipient_list=[emp.email],
                    html_message=html_body,
                )
                sent += 1
                self.stdout.write(self.style.SUCCESS(f"Sent to {emp.email}"))
            except Exception as e:
                skipped += 1
                self.stderr.write(self.style.ERROR(f"Failed for {emp.email}: {e}"))

        self.stdout.write(
            self.style.SUCCESS(f"\nDone. Sent: {sent}, Failed: {skipped}")
        )
