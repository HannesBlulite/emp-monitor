"""
Monitoring App — Models

Core data models for employee monitoring:
- Employee: Tracked employee linked to a Django user
- AgentToken: Authentication token for agent-to-server communication
- Screenshot: Captured screenshots with metadata
- ActivityLog: Periodic activity summaries (active/idle time, app usage)
- AppUsageEntry: Per-app usage breakdown within an activity period
- ProductivityRule: Website/app categorization (productive/unproductive/neutral)
- AgentSettings: Global and per-employee agent configuration
"""

import secrets
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Employee(models.Model):
    """An employee being monitored."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    employee_id = models.CharField(max_length=50, unique=True, help_text="Internal employee ID")
    display_name = models.CharField(max_length=200)
    email = models.EmailField(blank=True, default='', help_text="Employee email for daily timesheet reports")
    department = models.CharField(max_length=100, blank=True)
    pc_name = models.CharField(max_length=100, blank=True, help_text="Computer name")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_name']

    def __str__(self):
        return f"{self.display_name} ({self.employee_id})"

    @property
    def today_active_time(self):
        """Get total active seconds for today."""
        today = timezone.now().date()
        result = self.activity_logs.filter(
            created_at__date=today
        ).aggregate(total=models.Sum('active_seconds'))
        return result['total'] or 0

    @property
    def last_seen(self):
        """Get the timestamp of the last activity."""
        latest = self.activity_logs.order_by('-created_at').first()
        if latest:
            return latest.created_at
        return None


class AgentToken(models.Model):
    """Authentication token for agent-to-server communication."""
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name='agent_token')
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_hex(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Token for {self.employee.display_name}"


class Screenshot(models.Model):
    """A captured screenshot from an employee's monitor."""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='screenshots')
    image = models.ImageField(upload_to='screenshots/%Y/%m/%d/')
    monitor_index = models.PositiveSmallIntegerField(default=1)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    file_size = models.PositiveIntegerField(default=0, help_text="File size in bytes")
    captured_at = models.DateTimeField(help_text="When the screenshot was taken on the employee PC")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-captured_at']
        indexes = [
            models.Index(fields=['employee', '-captured_at']),
        ]

    def __str__(self):
        return f"Screenshot {self.employee.display_name} Mon{self.monitor_index} @ {self.captured_at}"


class ActivityLog(models.Model):
    """Periodic activity summary from an employee's machine."""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='activity_logs')
    active_seconds = models.FloatField(default=0)
    idle_seconds = models.FloatField(default=0)
    total_seconds = models.FloatField(default=0)
    productivity_ratio = models.FloatField(default=0, help_text="0.0 to 1.0")
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['employee', '-created_at']),
        ]

    def __str__(self):
        return (
            f"Activity {self.employee.display_name} "
            f"Active:{self.active_seconds:.0f}s Idle:{self.idle_seconds:.0f}s"
        )


class AppUsageEntry(models.Model):
    """Individual app usage entry within an activity log."""
    activity_log = models.ForeignKey(
        ActivityLog, on_delete=models.CASCADE, related_name='app_entries'
    )
    process_name = models.CharField(max_length=200)
    window_title = models.TextField(blank=True)
    domain = models.CharField(
        max_length=200, blank=True, default='',
        help_text="Extracted website domain when the active app is a browser"
    )
    duration_seconds = models.FloatField(default=0)
    timestamp = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-duration_seconds']

    def __str__(self):
        return f"{self.process_name}: {self.duration_seconds:.0f}s"


class ProductivityCategory(models.TextChoices):
    PRODUCTIVE = 'productive', 'Productive'
    UNPRODUCTIVE = 'unproductive', 'Unproductive'
    NEUTRAL = 'neutral', 'Neutral'


class ProductivityRule(models.Model):
    """
    Rules for classifying websites and apps as productive/unproductive.
    Used by the dashboard to calculate productivity scores.
    """
    MATCH_TYPE_CHOICES = [
        ('domain', 'Website Domain'),
        ('app', 'Application'),
    ]

    match_type = models.CharField(max_length=10, choices=MATCH_TYPE_CHOICES)
    pattern = models.CharField(
        max_length=200,
        help_text="Domain name (e.g. 'github.com') or app name (e.g. 'code.exe')"
    )
    category = models.CharField(
        max_length=20,
        choices=ProductivityCategory.choices,
        default=ProductivityCategory.NEUTRAL,
    )
    description = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['match_type', 'pattern']
        unique_together = ['match_type', 'pattern']

    def __str__(self):
        return f"{self.get_match_type_display()}: {self.pattern} → {self.category}"


class AgentSettings(models.Model):
    """
    Global agent settings. Only one record should exist (singleton).
    Individual employee overrides can be added later.
    """
    screenshot_interval_seconds = models.PositiveIntegerField(
        default=300, help_text="How often to take screenshots (in seconds)"
    )
    activity_report_interval_seconds = models.PositiveIntegerField(
        default=60, help_text="How often to send activity reports (in seconds)"
    )
    idle_threshold_seconds = models.PositiveIntegerField(
        default=120, help_text="Seconds of no input before marking as idle"
    )
    screenshot_quality = models.PositiveSmallIntegerField(
        default=60, help_text="JPEG quality (1-100)"
    )
    tracking_enabled = models.BooleanField(
        default=True, help_text="Master switch to enable/disable all tracking"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Agent Settings"

    def __str__(self):
        return (
            f"Settings: Screenshots every {self.screenshot_interval_seconds}s, "
            f"Activity every {self.activity_report_interval_seconds}s"
        )

    @classmethod
    def get_settings(cls):
        """Get the singleton settings instance, creating defaults if needed."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Notification(models.Model):
    """
    Notification sent from the server (manager) to an employee's agent.
    The agent polls for pending notifications and displays them as
    Windows toast notifications on the employee's PC.
    """
    NOTIFICATION_TYPES = [
        ('overtime', 'Overtime Info'),
        ('schedule', 'Schedule Info'),
        ('custom', 'Custom Message'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='custom')
    title = models.CharField(max_length=200)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True, help_text="When the agent displayed the toast")
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['employee', '-created_at']),
            models.Index(fields=['employee', 'delivered_at']),
        ]

    def __str__(self):
        status = 'delivered' if self.delivered_at else 'pending'
        return f"[{status}] {self.title} → {self.employee.display_name}"


class AgentPackage(models.Model):
    """
    Uploaded agent update package. The latest active package is served
    to agents that request an update.
    """
    version = models.CharField(max_length=20, unique=True, help_text="Semver e.g. 1.1.0")
    package = models.FileField(upload_to='agent_packages/')
    notes = models.TextField(blank=True, help_text="What changed in this version")
    is_active = models.BooleanField(default=True, help_text="Serve this version to agents")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Agent v{self.version}{' (active)' if self.is_active else ''}"


class AgentCommand(models.Model):
    """
    Queued commands issued by a manager to be picked up by an employee's agent.
    The agent polls for pending commands and executes them
    (e.g. restart, force-update).
    """
    COMMAND_CHOICES = [
        ('restart', 'Restart Agent'),
        ('update', 'Force Update'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='agent_commands')
    command = models.CharField(max_length=20, choices=COMMAND_CHOICES)
    issued_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True, help_text="When the agent picked up the command")

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['employee', 'acknowledged_at']),
        ]

    def __str__(self):
        status = 'done' if self.acknowledged_at else 'pending'
        return f"[{status}] {self.command} → {self.employee.display_name}"
