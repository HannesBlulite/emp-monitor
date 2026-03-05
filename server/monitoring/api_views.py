"""
Monitoring App — API Views

REST API endpoints for agent-to-server communication:
- Screenshot upload
- Activity report upload
- Settings retrieval
"""

import logging
from datetime import datetime

from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import (
    Employee, AgentToken, Screenshot, ActivityLog,
    AppUsageEntry, AgentSettings,
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

    # Save window log entries
    window_log = data.get('window_log', [])
    for entry in window_log:
        ts_str = entry.get('timestamp', '')
        try:
            ts = datetime.fromisoformat(ts_str)
            if not ts.tzinfo:
                ts = timezone.make_aware(ts)
        except (ValueError, TypeError):
            ts = None

        AppUsageEntry.objects.create(
            activity_log=activity_log,
            process_name=entry.get('process_name', 'unknown'),
            window_title=entry.get('window_title', ''),
            duration_seconds=float(entry.get('duration_seconds', 0)),
            timestamp=ts,
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
