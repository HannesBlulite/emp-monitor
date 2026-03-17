"""
Monitoring App — Dashboard Views

Web dashboard views for the admin/manager to view employee data.
"""

import json
from collections import defaultdict
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Avg, Max
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from .models import (
    Employee, Screenshot, ActivityLog, AppUsageEntry,
    ProductivityRule, AgentSettings, AgentToken,
)


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

        # Online status — consider "online" if activity within last 5 minutes
        is_online = False
        if last_log:
            is_online = (timezone.now() - last_log.created_at) < timedelta(minutes=5)

        active_secs = today_summary['total_active'] or 0
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
        screenshots = all_day_screenshots.filter(
            captured_at__hour=selected_hour,
        )
    else:
        screenshots = all_day_screenshots.none()  # hidden until a slot is picked

    # Build time slots with screenshot counts for the picker
    from django.db.models.functions import ExtractHour
    hour_counts = dict(
        all_day_screenshots
        .annotate(hour=ExtractHour('captured_at'))
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

    # Classify apps by productivity rules
    rules = {r.pattern.lower(): r.category for r in ProductivityRule.objects.all()}
    classified_apps = []
    for app in app_usage:
        name = app['process_name']
        category = rules.get(name.lower(), 'neutral')
        classified_apps.append({
            'process_name': name,
            'duration_seconds': app['total_duration'],
            'duration_minutes': round(app['total_duration'] / 60, 1),
            'category': category,
        })

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
        'app_usage': classified_apps,
        'total_screenshots': total_day_screenshots,
        'filtered_screenshot_count': screenshots.count(),
        'time_slots': time_slots,
        'selected_hour': selected_hour,
    }

    return render(request, 'monitoring/employee_detail.html', context)


@login_required
def settings_view(request):
    """Admin settings page."""
    settings = AgentSettings.get_settings()
    rules = ProductivityRule.objects.all()
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
                pattern=request.POST.get('pattern', ''),
                defaults={
                    'category': request.POST.get('category', 'neutral'),
                    'description': request.POST.get('description', ''),
                }
            )

        elif action == 'delete_rule':
            rule_id = request.POST.get('rule_id')
            if rule_id:
                ProductivityRule.objects.filter(id=rule_id).delete()

        elif action == 'add_employee':
            emp = Employee.objects.create(
                employee_id=request.POST.get('emp_id', ''),
                display_name=request.POST.get('emp_name', ''),
                department=request.POST.get('emp_department', ''),
                pc_name=request.POST.get('emp_pc_name', ''),
            )
            # Generate agent token
            token = AgentToken.objects.create(employee=emp)

        elif action == 'regenerate_token':
            emp_pk = request.POST.get('employee_pk')
            if emp_pk:
                emp = get_object_or_404(Employee, pk=emp_pk)
                AgentToken.objects.filter(employee=emp).delete()
                AgentToken.objects.create(employee=emp)

    # Reload after POST
    settings = AgentSettings.get_settings()
    rules = ProductivityRule.objects.all()
    employees = Employee.objects.all().order_by('display_name')

    # Include tokens for display
    employee_tokens = []
    for emp in employees:
        token = AgentToken.objects.filter(employee=emp).first()
        employee_tokens.append({
            'employee': emp,
            'token': token.token if token else 'No token',
            'last_used': token.last_used if token else None,
        })

    context = {
        'settings': settings,
        'rules': rules,
        'employee_tokens': employee_tokens,
    }

    return render(request, 'monitoring/settings.html', context)
