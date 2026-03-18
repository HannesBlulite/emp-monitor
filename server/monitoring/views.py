"""
Monitoring App — Dashboard Views

Web dashboard views for the admin/manager to view employee data.
"""

import csv
import io
import json
from collections import defaultdict
from datetime import timedelta, date as date_type, datetime as dt_type

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Avg, Max, Min, Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from .models import (
    Employee, Screenshot, ActivityLog, AppUsageEntry,
    ProductivityRule, AgentSettings, AgentToken,
)


def _match_domain_rule(domain, domain_rules):
    """
    Match a domain against productivity rules.
    Tries exact match first, then checks if the domain is a subdomain
    of any rule pattern (e.g. 'mail.google.com' matches 'google.com').
    """
    domain = domain.lower()
    # Exact match
    if domain in domain_rules:
        return domain_rules[domain]
    # Subdomain match: if domain ends with '.pattern'
    for pattern, category in domain_rules.items():
        if domain.endswith('.' + pattern):
            return category
    return 'neutral'


@login_required
def dashboard(request):
    """Main dashboard — overview of all employees."""
    today = timezone.now().date()

    employees = Employee.objects.filter(is_active=True).order_by('display_name')

    employee_data = []
    for emp in employees:
        # Today's activity summary
        today_logs = emp.activity_logs.filter(created_at__date=today)
        today_summary = today_logs.aggregate(
            total_active=Sum('active_seconds'),
            total_idle=Sum('idle_seconds'),
            avg_productivity=Avg('productivity_ratio'),
        )

        # Latest screenshot
        latest_screenshot = emp.screenshots.first()

        # Last seen (last activity log)
        last_log = emp.activity_logs.first()

        active_secs = today_summary['total_active'] or 0

        # Online = has active time today (agent working) or seen in last 10 min
        is_online = False
        if last_log:
            recently_seen = (timezone.now() - last_log.created_at) < timedelta(minutes=10)
            is_online = recently_seen or active_secs > 0
        idle_secs = today_summary['total_idle'] or 0
        total_secs = active_secs + idle_secs

        employee_data.append({
            'employee': emp,
            'active_seconds': active_secs,
            'active_hours': round(active_secs / 3600, 1),
            'idle_seconds': idle_secs,
            'productivity': round((today_summary['avg_productivity'] or 0) * 100),
            'latest_screenshot': latest_screenshot,
            'last_seen': last_log.created_at if last_log else None,
            'is_online': is_online,
            'total_screenshots_today': emp.screenshots.filter(captured_at__date=today).count(),
        })

    # Global stats
    total_employees = employees.count()
    online_count = sum(1 for e in employee_data if e['is_online'])

    settings = AgentSettings.get_settings()

    context = {
        'employee_data': employee_data,
        'total_employees': total_employees,
        'online_count': online_count,
        'offline_count': total_employees - online_count,
        'settings': settings,
        'today': today,
    }

    return render(request, 'monitoring/dashboard.html', context)


@login_required
def employee_detail(request, employee_id):
    """Detailed view for a specific employee."""
    employee = get_object_or_404(Employee, employee_id=employee_id)

    # Date filter (default: today)
    date_str = request.GET.get('date')
    if date_str:
        try:
            from datetime import date as date_cls
            selected_date = date_cls.fromisoformat(date_str)
        except ValueError:
            selected_date = timezone.now().date()
    else:
        selected_date = timezone.now().date()

    # Screenshots for selected date
    all_day_screenshots = employee.screenshots.filter(
        captured_at__date=selected_date
    ).order_by('-captured_at')

    # Hour filter — optional, e.g. ?hour=8 means 08:00–08:59
    hour_str = request.GET.get('hour')
    selected_hour = None
    if hour_str is not None:
        try:
            selected_hour = int(hour_str)
            if not (0 <= selected_hour <= 23):
                selected_hour = None
        except (ValueError, TypeError):
            selected_hour = None

    if selected_hour is not None:
        from datetime import datetime as dt, time
        import zoneinfo
        local_tz = zoneinfo.ZoneInfo('Africa/Johannesburg')
        slot_start = timezone.make_aware(dt.combine(selected_date, time(selected_hour, 0)), local_tz)
        slot_end = timezone.make_aware(dt.combine(selected_date, time(selected_hour, 59, 59)), local_tz)
        screenshots = all_day_screenshots.filter(
            captured_at__gte=slot_start,
            captured_at__lte=slot_end,
        )
    else:
        screenshots = all_day_screenshots.none()  # hidden until a slot is picked

    # Build time slots with screenshot counts for the picker
    from django.db.models.functions import ExtractHour
    import zoneinfo
    local_tz = zoneinfo.ZoneInfo('Africa/Johannesburg')
    hour_counts = dict(
        all_day_screenshots
        .annotate(hour=ExtractHour('captured_at', tzinfo=local_tz))
        .values('hour')
        .annotate(count=Count('id'))
        .values_list('hour', 'count')
    )
    time_slots = []
    for h in range(24):
        count = hour_counts.get(h, 0)
        if count > 0:
            time_slots.append({
                'hour': h,
                'label': f"{h:02d}:00 – {h:02d}:59",
                'count': count,
                'active': selected_hour == h,
            })

    # Activity logs for selected date
    activity_logs = employee.activity_logs.filter(
        created_at__date=selected_date
    ).order_by('-created_at')

    # Activity summary
    summary = activity_logs.aggregate(
        total_active=Sum('active_seconds'),
        total_idle=Sum('idle_seconds'),
        avg_productivity=Avg('productivity_ratio'),
    )

    active_secs = summary['total_active'] or 0
    idle_secs = summary['total_idle'] or 0

    # App usage breakdown for the day
    app_usage = AppUsageEntry.objects.filter(
        activity_log__employee=employee,
        activity_log__created_at__date=selected_date,
    ).values('process_name').annotate(
        total_duration=Sum('duration_seconds')
    ).order_by('-total_duration')[:20]

    # Domain (website) usage breakdown for the day
    domain_usage = AppUsageEntry.objects.filter(
        activity_log__employee=employee,
        activity_log__created_at__date=selected_date,
    ).exclude(domain='').values('domain').annotate(
        total_duration=Sum('duration_seconds')
    ).order_by('-total_duration')[:20]

    # Build rule lookup dicts
    app_rules = {
        r.pattern.lower(): r.category
        for r in ProductivityRule.objects.filter(match_type='app')
    }
    domain_rules = {
        r.pattern.lower(): r.category
        for r in ProductivityRule.objects.filter(match_type='domain')
    }

    # Classify apps
    classified_apps = []
    for app in app_usage:
        name = app['process_name']
        # Skip the synthetic [website] entries — those are in domain_usage
        if name == '[website]':
            continue
        app_key = name.lower().replace('.exe', '')
        category = app_rules.get(app_key, app_rules.get(name.lower(), 'neutral'))
        classified_apps.append({
            'process_name': name,
            'duration_seconds': app['total_duration'],
            'duration_minutes': round(app['total_duration'] / 60, 1),
            'category': category,
        })

    # Classify websites
    classified_websites = []
    productive_seconds = 0
    unproductive_seconds = 0
    neutral_seconds = 0
    for site in domain_usage:
        domain = site['domain']
        category = _match_domain_rule(domain, domain_rules)
        dur = site['total_duration']
        classified_websites.append({
            'domain': domain,
            'duration_seconds': dur,
            'duration_minutes': round(dur / 60, 1),
            'category': category,
        })
        if category == 'productive':
            productive_seconds += dur
        elif category == 'unproductive':
            unproductive_seconds += dur
        else:
            neutral_seconds += dur

    # Also count app-based productivity
    for app in classified_apps:
        if app['category'] == 'productive':
            productive_seconds += app['duration_seconds']
        elif app['category'] == 'unproductive':
            unproductive_seconds += app['duration_seconds']
        else:
            neutral_seconds += app['duration_seconds']

    # Rule-based productivity percentage
    classified_total = productive_seconds + unproductive_seconds + neutral_seconds
    rule_productivity_pct = (
        round(productive_seconds / classified_total * 100)
        if classified_total > 0 else 0
    )

    total_day_screenshots = all_day_screenshots.count()

    context = {
        'employee': employee,
        'selected_date': selected_date,
        'screenshots': screenshots,
        'activity_logs': activity_logs,
        'active_seconds': active_secs,
        'active_hours': round(active_secs / 3600, 1),
        'idle_seconds': idle_secs,
        'idle_hours': round(idle_secs / 3600, 1),
        'productivity_pct': round((summary['avg_productivity'] or 0) * 100),
        'rule_productivity_pct': rule_productivity_pct,
        'productive_seconds': round(productive_seconds),
        'unproductive_seconds': round(unproductive_seconds),
        'neutral_seconds': round(neutral_seconds),
        'app_usage': classified_apps,
        'website_usage': classified_websites,
        'total_screenshots': total_day_screenshots,
        'filtered_screenshot_count': screenshots.count(),
        'time_slots': time_slots,
        'selected_hour': selected_hour,
    }

    return render(request, 'monitoring/employee_detail.html', context)


@login_required
def timesheets(request):
    """Timesheets view — all employees with clock-in/out, hours, productivity."""
    today = timezone.now().date()

    # Parse date range
    date_from_str = request.GET.get('date_from')
    date_to_str = request.GET.get('date_to')
    preset = request.GET.get('preset', '')

    if preset == 'yesterday':
        date_from = today - timedelta(days=1)
        date_to = date_from
    elif preset == 'last7':
        date_from = today - timedelta(days=6)
        date_to = today
    elif preset == 'last30':
        date_from = today - timedelta(days=29)
        date_to = today
    elif preset == 'this_month':
        date_from = today.replace(day=1)
        date_to = today
    elif preset == 'last_month':
        first_of_this = today.replace(day=1)
        last_month_end = first_of_this - timedelta(days=1)
        date_from = last_month_end.replace(day=1)
        date_to = last_month_end
    elif date_from_str and date_to_str:
        try:
            date_from = date_type.fromisoformat(date_from_str)
            date_to = date_type.fromisoformat(date_to_str)
        except ValueError:
            date_from = today
            date_to = today
    else:
        date_from = today
        date_to = today

    # Ensure order
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    # Build rule lookup dicts
    app_rules = {
        r.pattern.lower(): r.category
        for r in ProductivityRule.objects.filter(match_type='app')
    }
    domain_rules = {
        r.pattern.lower(): r.category
        for r in ProductivityRule.objects.filter(match_type='domain')
    }

    employees = Employee.objects.filter(is_active=True).order_by('display_name')
    rows = []

    for emp in employees:
        logs = emp.activity_logs.filter(
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
        )

        if not logs.exists():
            continue

        summary = logs.aggregate(
            total_active=Sum('active_seconds'),
            total_idle=Sum('idle_seconds'),
        )

        active_secs = summary['total_active'] or 0
        idle_secs = summary['total_idle'] or 0
        total_secs = active_secs + idle_secs

        # Clock in = earliest activity, clock out = latest activity
        times = logs.aggregate(
            clock_in=Min('created_at'),
            clock_out=Max('created_at'),
        )
        clock_in = times['clock_in']
        clock_out = times['clock_out']

        # Calculate total office hours from clock in to clock out
        if clock_in and clock_out and clock_out > clock_in:
            office_secs = (clock_out - clock_in).total_seconds()
        else:
            office_secs = total_secs

        # Productivity classification
        app_usage = AppUsageEntry.objects.filter(
            activity_log__employee=emp,
            activity_log__created_at__date__gte=date_from,
            activity_log__created_at__date__lte=date_to,
        )

        productive_secs = 0
        unproductive_secs = 0

        # App-based classification
        app_totals = app_usage.filter(domain='').values('process_name').annotate(
            total=Sum('duration_seconds')
        )
        for entry in app_totals:
            name = entry['process_name']
            if name == '[website]':
                continue
            app_key = name.lower().replace('.exe', '')
            cat = app_rules.get(app_key, app_rules.get(name.lower(), 'neutral'))
            if cat == 'productive':
                productive_secs += entry['total']
            elif cat == 'unproductive':
                unproductive_secs += entry['total']

        # Domain-based classification
        domain_totals = app_usage.exclude(domain='').values('domain').annotate(
            total=Sum('duration_seconds')
        )
        for entry in domain_totals:
            cat = _match_domain_rule(entry['domain'], domain_rules)
            if cat == 'productive':
                productive_secs += entry['total']
            elif cat == 'unproductive':
                unproductive_secs += entry['total']

        # Productivity percentage = productive / active
        productivity_pct = (
            round(productive_secs / active_secs * 100, 1)
            if active_secs > 0 else 0
        )

        rows.append({
            'employee': emp,
            'clock_in': clock_in,
            'clock_out': clock_out,
            'total_hours': _fmt_duration(total_secs),
            'office_hours': _fmt_duration(office_secs),
            'active_hours': _fmt_duration(active_secs),
            'productive_hours': _fmt_duration(productive_secs),
            'unproductive_hours': _fmt_duration(unproductive_secs),
            'productivity_pct': productivity_pct,
        })

    context = {
        'rows': rows,
        'date_from': date_from,
        'date_to': date_to,
        'preset': preset,
    }
    return render(request, 'monitoring/timesheets.html', context)


def _fmt_duration(seconds):
    """Format seconds as HH:MM:SS."""
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


@login_required
def settings_view(request):
    """Admin settings page."""
    settings = AgentSettings.get_settings()
    employees = Employee.objects.all().order_by('display_name')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_settings':
            settings.screenshot_interval_seconds = int(
                request.POST.get('screenshot_interval', settings.screenshot_interval_seconds)
            )
            settings.activity_report_interval_seconds = int(
                request.POST.get('activity_interval', settings.activity_report_interval_seconds)
            )
            settings.idle_threshold_seconds = int(
                request.POST.get('idle_threshold', settings.idle_threshold_seconds)
            )
            settings.screenshot_quality = int(
                request.POST.get('screenshot_quality', settings.screenshot_quality)
            )
            settings.tracking_enabled = request.POST.get('tracking_enabled') == 'on'
            settings.save()

        elif action == 'add_rule':
            ProductivityRule.objects.get_or_create(
                match_type=request.POST.get('match_type', 'domain'),
                pattern=request.POST.get('pattern', '').strip().lower(),
                defaults={
                    'category': request.POST.get('category', 'neutral'),
                    'description': request.POST.get('description', ''),
                }
            )

        elif action == 'edit_rule':
            rule_id = request.POST.get('rule_id')
            if rule_id:
                ProductivityRule.objects.filter(id=rule_id).update(
                    match_type=request.POST.get('match_type', 'domain'),
                    pattern=request.POST.get('pattern', '').strip().lower(),
                    category=request.POST.get('category', 'neutral'),
                    description=request.POST.get('description', ''),
                )

        elif action == 'delete_rule':
            rule_id = request.POST.get('rule_id')
            if rule_id:
                ProductivityRule.objects.filter(id=rule_id).delete()

        elif action == 'import_rules':
            csv_file = request.FILES.get('csv_file')
            if csv_file:
                _import_rules_from_csv(csv_file)

        elif action == 'add_employee':
            emp = Employee.objects.create(
                employee_id=request.POST.get('emp_id', ''),
                display_name=request.POST.get('emp_name', ''),
                department=request.POST.get('emp_department', ''),
                pc_name=request.POST.get('emp_pc_name', ''),
            )
            AgentToken.objects.create(employee=emp)

        elif action == 'regenerate_token':
            emp_pk = request.POST.get('employee_pk')
            if emp_pk:
                emp = get_object_or_404(Employee, pk=emp_pk)
                AgentToken.objects.filter(employee=emp).delete()
                AgentToken.objects.create(employee=emp)

    # Reload after POST
    settings = AgentSettings.get_settings()

    # Rules — with search and pagination
    rule_search = request.GET.get('rule_search', '').strip()
    rule_type_filter = request.GET.get('rule_type', '')
    rule_category_filter = request.GET.get('rule_category', '')

    rules_qs = ProductivityRule.objects.all()
    if rule_search:
        rules_qs = rules_qs.filter(pattern__icontains=rule_search)
    if rule_type_filter:
        rules_qs = rules_qs.filter(match_type=rule_type_filter)
    if rule_category_filter:
        rules_qs = rules_qs.filter(category=rule_category_filter)

    total_rules = rules_qs.count()

    # Simple pagination
    page = int(request.GET.get('rule_page', 1))
    per_page = 50
    total_pages = max(1, (total_rules + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    rules = rules_qs[(page - 1) * per_page: page * per_page]

    employees = Employee.objects.all().order_by('display_name')
    employee_tokens = []
    for emp in employees:
        token = AgentToken.objects.filter(employee=emp).first()
        employee_tokens.append({
            'employee': emp,
            'token': token.token if token else 'No token',
            'last_used': token.last_used if token else None,
        })

    # Rule counts for display
    rule_counts = {
        'total': ProductivityRule.objects.count(),
        'productive': ProductivityRule.objects.filter(category='productive').count(),
        'unproductive': ProductivityRule.objects.filter(category='unproductive').count(),
        'neutral': ProductivityRule.objects.filter(category='neutral').count(),
        'websites': ProductivityRule.objects.filter(match_type='domain').count(),
        'apps': ProductivityRule.objects.filter(match_type='app').count(),
    }

    context = {
        'settings': settings,
        'rules': rules,
        'total_rules': total_rules,
        'rule_search': rule_search,
        'rule_type_filter': rule_type_filter,
        'rule_category_filter': rule_category_filter,
        'rule_page': page,
        'total_pages': total_pages,
        'page_range': range(max(1, page - 3), min(total_pages + 1, page + 4)),
        'rule_counts': rule_counts,
        'employee_tokens': employee_tokens,
    }

    return render(request, 'monitoring/settings.html', context)


def _import_rules_from_csv(csv_file):
    """Import productivity rules from an uploaded CSV file."""
    decoded = csv_file.read().decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(decoded))

    type_map = {'website': 'domain', 'application': 'app'}
    category_map = {'productive': 'productive', 'unproductive': 'unproductive', 'neutral': 'neutral'}

    created = 0
    updated = 0
    for row in reader:
        raw = {k.strip().lower(): v for k, v in row.items()}
        raw_type = raw.get('type', '').strip().lower()
        pattern = raw.get('activity', raw.get('pattern', '')).strip().lower()
        raw_status = raw.get('status', raw.get('category', '')).strip().lower()

        match_type = type_map.get(raw_type)
        category = category_map.get(raw_status, 'neutral')

        if not match_type or not pattern:
            continue

        _, was_created = ProductivityRule.objects.update_or_create(
            match_type=match_type,
            pattern=pattern,
            defaults={'category': category},
        )
        if was_created:
            created += 1
        else:
            updated += 1

    return created, updated


@login_required
def export_rules_csv(request):
    """Export all productivity rules as a CSV download."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="productivity_rules.csv"'

    writer = csv.writer(response)
    writer.writerow(['Type', 'Activity', 'status'])

    type_map = {'domain': 'Website', 'app': 'Application'}
    category_map = {'productive': 'Productive', 'unproductive': 'Unproductive', 'neutral': 'Neutral'}

    for rule in ProductivityRule.objects.all().order_by('match_type', 'pattern'):
        writer.writerow([
            type_map.get(rule.match_type, rule.match_type),
            rule.pattern,
            category_map.get(rule.category, rule.category),
        ])

    return response
