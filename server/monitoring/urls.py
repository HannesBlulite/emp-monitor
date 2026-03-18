"""
Monitoring App — URL Configuration
"""

from django.urls import path
from . import views, api_views

app_name = 'monitoring'

urlpatterns = [
    # Dashboard views
    path('', views.dashboard, name='dashboard'),
    path('employee/<str:employee_id>/', views.employee_detail, name='employee_detail'),
    path('settings/', views.settings_view, name='settings'),
    path('settings/export-rules/', views.export_rules_csv, name='export_rules_csv'),

    # API endpoints (for agent communication)
    path('api/screenshots/upload/', api_views.screenshot_upload, name='api_screenshot_upload'),
    path('api/activity/report/', api_views.activity_report, name='api_activity_report'),
    path('api/agent/settings/', api_views.agent_settings, name='api_agent_settings'),
    path('api/agent/update/check/', api_views.agent_update_check, name='api_agent_update_check'),
    path('api/agent/update/download/<int:pk>/', api_views.agent_update_download, name='api_agent_update_download'),
]
