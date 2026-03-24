"""
Monitoring App — Admin Configuration
"""

from django.contrib import admin
from .models import (
    Employee, AgentToken, Screenshot, ActivityLog,
    AppUsageEntry, ProductivityRule, AgentSettings, AgentPackage,
    Notification, AgentCommand,
)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ['display_name', 'employee_id', 'email', 'department', 'pc_name', 'last_ip', 'agent_version', 'is_active', 'created_at']
    list_filter = ['is_active', 'department']
    search_fields = ['display_name', 'employee_id', 'pc_name', 'email']
    readonly_fields = ['last_ip', 'agent_version']


@admin.register(AgentToken)
class AgentTokenAdmin(admin.ModelAdmin):
    list_display = ['employee', 'token', 'created_at', 'last_used']
    readonly_fields = ['token']


@admin.register(Screenshot)
class ScreenshotAdmin(admin.ModelAdmin):
    list_display = ['employee', 'monitor_index', 'width', 'height', 'file_size', 'captured_at']
    list_filter = ['employee', 'monitor_index', 'captured_at']
    date_hierarchy = 'captured_at'


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ['employee', 'active_seconds', 'idle_seconds', 'productivity_ratio', 'created_at']
    list_filter = ['employee', 'created_at']
    date_hierarchy = 'created_at'


@admin.register(AppUsageEntry)
class AppUsageEntryAdmin(admin.ModelAdmin):
    list_display = ['activity_log', 'process_name', 'duration_seconds', 'timestamp']
    list_filter = ['process_name']
    search_fields = ['process_name', 'window_title']


@admin.register(ProductivityRule)
class ProductivityRuleAdmin(admin.ModelAdmin):
    list_display = ['match_type', 'pattern', 'category', 'description']
    list_filter = ['match_type', 'category']
    search_fields = ['pattern', 'description']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['employee', 'notification_type', 'title', 'created_at', 'delivered_at']
    list_filter = ['notification_type', 'delivered_at']
    search_fields = ['title', 'message', 'employee__display_name']


@admin.register(AgentSettings)
class AgentSettingsAdmin(admin.ModelAdmin):
    list_display = [
        'screenshot_interval_seconds', 'activity_report_interval_seconds',
        'idle_threshold_seconds', 'tracking_enabled', 'updated_at'
    ]


@admin.register(AgentPackage)
class AgentPackageAdmin(admin.ModelAdmin):
    list_display = ['version', 'is_active', 'notes', 'created_at']
    list_filter = ['is_active']
    readonly_fields = ['created_at']


@admin.register(AgentCommand)
class AgentCommandAdmin(admin.ModelAdmin):
    list_display = ['employee', 'command', 'issued_by', 'created_at', 'acknowledged_at']
    list_filter = ['command', 'acknowledged_at']
    search_fields = ['employee__display_name']
    readonly_fields = ['created_at']
