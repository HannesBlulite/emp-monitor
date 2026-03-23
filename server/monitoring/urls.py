"""
Monitoring App — URL Configuration
"""

from django.urls import path
from . import views, api_views

app_name = 'monitoring'

urlpatterns = [
    # Dashboard views
    path('', views.dashboard, name='dashboard'),
    path('timesheets/', views.timesheets, name='timesheets'),
    path('employee/<str:employee_id>/', views.employee_detail, name='employee_detail'),
    path('settings/', views.settings_view, name='settings'),
    path('settings/export-rules/', views.export_rules_csv, name='export_rules_csv'),

    # AJAX endpoints for inline rule editing
    path('api/rules/update-category/', views.ajax_update_rule_category, name='ajax_update_rule_category'),
    path('api/rules/bulk-action/', views.ajax_bulk_rule_action, name='ajax_bulk_rule_action'),

    # API endpoints (for agent communication)
    path('api/screenshots/upload/', api_views.screenshot_upload, name='api_screenshot_upload'),
    path('api/activity/report/', api_views.activity_report, name='api_activity_report'),
    path('api/agent/settings/', api_views.agent_settings, name='api_agent_settings'),
    path('api/agent/update/check/', api_views.agent_update_check, name='api_agent_update_check'),
    path('api/agent/update/download/<int:pk>/', api_views.agent_update_download, name='api_agent_update_download'),

    # Notification endpoints
    path('api/notifications/pending/', api_views.notifications_pending, name='api_notifications_pending'),
    path('api/notifications/<int:pk>/ack/', api_views.notification_ack, name='api_notification_ack'),
    path('api/notifications/send/', api_views.send_notification, name='api_send_notification'),

    # Agent command endpoints (remote restart / update)
    path('api/agent/commands/pending/', api_views.agent_commands_pending, name='api_agent_commands_pending'),
    path('api/agent/commands/<int:pk>/ack/', api_views.agent_command_ack, name='api_agent_command_ack'),
    path('api/agent/commands/issue/', api_views.issue_agent_command, name='api_issue_agent_command'),
]
