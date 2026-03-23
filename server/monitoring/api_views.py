"""
Monitoring App — API Views

REST API endpoints for agent-to-server communication:
- Screenshot upload
- Activity report upload
- Settings retrieval
"""

import logging
import re
from datetime import datetime, timedelta

from django.core.files.base import ContentFile
from django.http import FileResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


class CsrfExemptSessionAuth(SessionAuthentication):
    """Session auth without CSRF enforcement (for AJAX from our own templates)."""
    def enforce_csrf(self, request):
        return


from .models import (
    Employee, AgentToken, Screenshot, ActivityLog,
    AppUsageEntry, AgentSettings, AgentPackage, ProductivityRule,
    Notification, AgentCommand,
)

logger = logging.getLogger('monitoring.api')


def authenticate_agent(request):
    """
    Authenticate an agent using its token from the Authorization header.
    Returns the Employee or None.
    """
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if auth_header.startswith('Token '):
        token_value = auth_header[6:]
        try:
            agent_token = AgentToken.objects.select_related('employee').get(token=token_value)
            agent_token.last_used = timezone.now()
            agent_token.save(update_fields=['last_used'])
            return agent_token.employee
        except AgentToken.DoesNotExist:
            pass
    return None


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def screenshot_upload(request):
    """
    API endpoint for agents to upload screenshots.

    Expected:
        - Multipart form with 'image' file
        - Fields: monitor_index, width, height, timestamp
    """
    employee = authenticate_agent(request)
    if not employee:
        return Response(
            {'error': 'Invalid or missing agent token'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    image_file = request.FILES.get('image')
    if not image_file:
        return Response(
            {'error': 'No image file provided'},
            status=status.HTTP_400_BAD_REQUEST
        )

    monitor_index = int(request.data.get('monitor_index', 1))
    width = int(request.data.get('width', 0))
    height = int(request.data.get('height', 0))
    timestamp_str = request.data.get('timestamp', '')

    try:
        captured_at = datetime.fromisoformat(timestamp_str)
        if not captured_at.tzinfo:
            captured_at = timezone.make_aware(captured_at)
    except (ValueError, TypeError):
        captured_at = timezone.now()

    screenshot = Screenshot.objects.create(
        employee=employee,
        image=image_file,
        monitor_index=monitor_index,
        width=width,
        height=height,
        file_size=image_file.size,
        captured_at=captured_at,
    )

    logger.info(
        f"Screenshot saved: {employee.display_name} monitor {monitor_index} "
        f"({width}x{height}, {image_file.size} bytes)"
    )

    return Response(
        {'status': 'ok', 'screenshot_id': screenshot.id},
        status=status.HTTP_201_CREATED
    )


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def activity_report(request):
    """
    API endpoint for agents to upload activity reports.

    Expected JSON:
    {
        "timestamp": "2026-02-21T05:30:00",
        "active_seconds": 55.0,
        "idle_seconds": 5.0,
        "total_seconds": 60.0,
        "productivity_ratio": 0.917,
        "app_usage": {"chrome.exe": 30.5, "code.exe": 20.0},
        "window_log": [
            {"timestamp": "...", "window_title": "...", "process_name": "...", "duration_seconds": 10.5}
        ]
    }
    """
    employee = authenticate_agent(request)
    if not employee:
        return Response(
            {'error': 'Invalid or missing agent token'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    data = request.data

    # ── Deduplication: reject if this employee reported within the last 30s ──
    recent_cutoff = timezone.now() - timedelta(seconds=30)
    if ActivityLog.objects.filter(employee=employee, created_at__gte=recent_cutoff).exists():
        return Response(
            {'status': 'duplicate_skipped'},
            status=status.HTTP_200_OK
        )

    activity_log = ActivityLog.objects.create(
        employee=employee,
        active_seconds=float(data.get('active_seconds', 0)),
        idle_seconds=float(data.get('idle_seconds', 0)),
        total_seconds=float(data.get('total_seconds', 0)),
        productivity_ratio=float(data.get('productivity_ratio', 0)),
    )

    # Save app usage entries
    app_usage = data.get('app_usage', {})
    for process_name, duration in app_usage.items():
        AppUsageEntry.objects.create(
            activity_log=activity_log,
            process_name=process_name,
            duration_seconds=float(duration),
        )

    # Save domain usage entries (website time tracked by browsing)
    domain_usage = data.get('domain_usage', {})
    for domain, duration in domain_usage.items():
        AppUsageEntry.objects.create(
            activity_log=activity_log,
            process_name='[website]',
            domain=domain,
            duration_seconds=float(duration),
        )

    # Save window log entries
    window_log = data.get('window_log', [])
    new_domains = set()
    new_apps = set()
    for entry in window_log:
        ts_str = entry.get('timestamp', '')
        try:
            ts = datetime.fromisoformat(ts_str)
            if not ts.tzinfo:
                ts = timezone.make_aware(ts)
        except (ValueError, TypeError):
            ts = None

        entry_domain = entry.get('domain', '')
        entry_process = entry.get('process_name', 'unknown')

        AppUsageEntry.objects.create(
            activity_log=activity_log,
            process_name=entry_process,
            window_title=entry.get('window_title', ''),
            domain=entry_domain,
            duration_seconds=float(entry.get('duration_seconds', 0)),
            timestamp=ts,
        )

        if entry_domain:
            new_domains.add(entry_domain)
        elif entry_process and entry_process not in ('[website]', 'unknown'):
            new_apps.add(entry_process.lower().replace('.exe', ''))

    # Also collect from app_usage and domain_usage dicts
    for domain in domain_usage:
        if domain:
            new_domains.add(domain)
    for process_name in app_usage:
        if process_name and process_name not in ('[website]', 'unknown'):
            new_apps.add(process_name.lower().replace('.exe', ''))

    # Auto-create neutral ProductivityRules for newly seen domains and apps
    _JUNK_DOMAIN = re.compile(
        r'\.pdf$|\.docx?$|\.xlsx?$|\.pptx?$|\.txt$|\.csv$'
        r'|\.png$|\.jpe?g$'
        r'|^[0-9a-f]{8}-[0-9a-f]{4}-'
        r'|^https?://'
        r'|\\'
        r'|^[\d.]+$'
        r'|@'
        r'|\|'
        r'|\.namespace\('
        r'|_[0-9a-f]{4,}_',
        re.IGNORECASE,
    )
    for domain in new_domains:
        if _JUNK_DOMAIN.search(domain):
            continue
        ProductivityRule.objects.get_or_create(
            match_type='domain',
            pattern=domain,
            defaults={
                'category': 'neutral',
                'description': f'Auto-added from {employee.display_name}',
            },
        )
    for app_name in new_apps:
        ProductivityRule.objects.get_or_create(
            match_type='app',
            pattern=app_name,
            defaults={
                'category': 'neutral',
                'description': f'Auto-added from {employee.display_name}',
            },
        )

    logger.info(
        f"Activity report saved: {employee.display_name} "
        f"Active:{data.get('active_seconds', 0):.0f}s "
        f"Idle:{data.get('idle_seconds', 0):.0f}s"
    )

    return Response(
        {'status': 'ok', 'activity_log_id': activity_log.id},
        status=status.HTTP_201_CREATED
    )


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def agent_settings(request):
    """
    API endpoint for agents to fetch their configuration.
    """
    employee = authenticate_agent(request)
    if not employee:
        return Response(
            {'error': 'Invalid or missing agent token'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    settings = AgentSettings.get_settings()

    return Response({
        'screenshot_interval_seconds': settings.screenshot_interval_seconds,
        'activity_report_interval_seconds': settings.activity_report_interval_seconds,
        'idle_threshold_seconds': settings.idle_threshold_seconds,
        'screenshot_quality': settings.screenshot_quality,
        'tracking_enabled': settings.tracking_enabled,
    })


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def agent_update_check(request):
    """
    Return the latest active agent version info.
    Agents poll this to see if an update is available.
    """
    employee = authenticate_agent(request)
    if not employee:
        return Response(
            {'error': 'Invalid or missing agent token'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    pkg = AgentPackage.objects.filter(is_active=True).first()
    if not pkg:
        return Response({'latest_version': '0.0.0', 'download_url': ''})

    return Response({
        'latest_version': pkg.version,
        'download_url': f'/api/agent/update/download/{pkg.pk}/',
        'notes': pkg.notes,
    })


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def agent_update_download(request, pk):
    """
    Serve the agent update ZIP file.
    """
    employee = authenticate_agent(request)
    if not employee:
        return Response(
            {'error': 'Invalid or missing agent token'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    try:
        pkg = AgentPackage.objects.get(pk=pk, is_active=True)
    except AgentPackage.DoesNotExist:
        return Response(
            {'error': 'Package not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    return FileResponse(
        pkg.package.open('rb'),
        content_type='application/zip',
        as_attachment=True,
        filename=f'empmonitor-agent-{pkg.version}.zip',
    )


# ---------------------------------------------------------------------------
# Notification endpoints
# ---------------------------------------------------------------------------

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def notifications_pending(request):
    """
    Return undelivered notifications for this agent's employee.
    The agent polls this endpoint every 60 seconds.
    """
    employee = authenticate_agent(request)
    if not employee:
        return Response(
            {'error': 'Invalid or missing agent token'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    pending = Notification.objects.filter(
        employee=employee,
        delivered_at__isnull=True,
    ).order_by('created_at')[:10]

    items = [
        {
            'id': n.id,
            'type': n.notification_type,
            'title': n.title,
            'message': n.message,
            'created_at': n.created_at.isoformat(),
        }
        for n in pending
    ]

    return Response({'notifications': items})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def notification_ack(request, pk):
    """
    Mark a notification as delivered (the agent displayed the toast).
    """
    employee = authenticate_agent(request)
    if not employee:
        return Response(
            {'error': 'Invalid or missing agent token'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    try:
        notification = Notification.objects.get(pk=pk, employee=employee)
    except Notification.DoesNotExist:
        return Response(
            {'error': 'Notification not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    if not notification.delivered_at:
        notification.delivered_at = timezone.now()
        notification.save(update_fields=['delivered_at'])

    return Response({'status': 'ok'})


@api_view(['POST'])
@authentication_classes([CsrfExemptSessionAuth])
def send_notification(request):
    """
    Manager endpoint: send a notification to one or more employees.
    Requires Django session auth (login_required via DRF default auth).

    Expected JSON:
    {
        "employee_ids": ["EMP001", "EMP002"],   // or ["all"]
        "title": "Overtime Info",
        "message": "You have 01:13 overtime today.",
        "notification_type": "overtime"          // optional, defaults to "custom"
    }
    """
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Authentication required'},
            status=status.HTTP_403_FORBIDDEN
        )

    data = request.data
    employee_ids = data.get('employee_ids', [])
    title = data.get('title', '').strip()
    message = data.get('message', '').strip()
    notification_type = data.get('notification_type', 'custom')

    if not title or not message:
        return Response(
            {'error': 'Title and message are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if notification_type not in ('overtime', 'schedule', 'custom'):
        notification_type = 'custom'

    if 'all' in employee_ids:
        employees = Employee.objects.filter(is_active=True)
    else:
        employees = Employee.objects.filter(employee_id__in=employee_ids, is_active=True)

    if not employees.exists():
        return Response(
            {'error': 'No matching employees found'},
            status=status.HTTP_400_BAD_REQUEST
        )

    created = []
    for emp in employees:
        n = Notification.objects.create(
            employee=emp,
            notification_type=notification_type,
            title=title,
            message=message,
        )
        created.append(n.id)

    logger.info(
        f"Notifications sent by {request.user.username}: "
        f"{len(created)} notification(s) — \"{title}\""
    )

    return Response(
        {'status': 'ok', 'count': len(created), 'notification_ids': created},
        status=status.HTTP_201_CREATED
    )


# ---------------------------------------------------------------------------
# Agent Command endpoints (remote restart / update)
# ---------------------------------------------------------------------------

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def agent_commands_pending(request):
    """
    Return unacknowledged commands for this agent's employee.
    The agent polls this alongside notification checks.
    """
    employee = authenticate_agent(request)
    if not employee:
        return Response(
            {'error': 'Invalid or missing agent token'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    pending = AgentCommand.objects.filter(
        employee=employee,
        acknowledged_at__isnull=True,
    ).order_by('created_at')[:10]

    items = [
        {
            'id': cmd.id,
            'command': cmd.command,
            'created_at': cmd.created_at.isoformat(),
        }
        for cmd in pending
    ]

    return Response({'commands': items})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def agent_command_ack(request, pk):
    """
    Mark a command as acknowledged (the agent received it and will act on it).
    """
    employee = authenticate_agent(request)
    if not employee:
        return Response(
            {'error': 'Invalid or missing agent token'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    try:
        cmd = AgentCommand.objects.get(pk=pk, employee=employee)
    except AgentCommand.DoesNotExist:
        return Response(
            {'error': 'Command not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    if not cmd.acknowledged_at:
        cmd.acknowledged_at = timezone.now()
        cmd.save(update_fields=['acknowledged_at'])

    return Response({'status': 'ok'})


@api_view(['POST'])
@authentication_classes([CsrfExemptSessionAuth])
def issue_agent_command(request):
    """
    Manager endpoint: issue a restart or update command to an employee's agent.
    Requires Django session auth.

    Expected JSON:
    {
        "employee_id": "EMP001",
        "command": "restart"     // or "update"
    }
    """
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Authentication required'},
            status=status.HTTP_403_FORBIDDEN
        )

    data = request.data
    employee_id = data.get('employee_id', '').strip()
    command = data.get('command', '').strip()

    if not employee_id or not command:
        return Response(
            {'error': 'employee_id and command are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if command not in ('restart', 'update'):
        return Response(
            {'error': 'Invalid command. Use "restart" or "update".'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        employee = Employee.objects.get(employee_id=employee_id, is_active=True)
    except Employee.DoesNotExist:
        return Response(
            {'error': 'Employee not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    cmd = AgentCommand.objects.create(
        employee=employee,
        command=command,
        issued_by=request.user,
    )

    logger.info(
        f"Agent command '{command}' issued for {employee.display_name} "
        f"by {request.user.username}"
    )

    return Response(
        {'status': 'ok', 'command_id': cmd.id},
        status=status.HTTP_201_CREATED
    )
