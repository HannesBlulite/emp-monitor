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

    # API endpoints (for agent communication)
    path('api/screenshots/upload/', api_views.screenshot_upload, name='api_screenshot_upload'),
    path('api/activity/report/', api_views.activity_report, name='api_activity_report'),
    path('api/agent/settings/', api_views.agent_settings, name='api_agent_settings'),
]
