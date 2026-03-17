from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from monitoring.models import ActivityLog, Screenshot


class Command(BaseCommand):
    help = 'Delete old screenshots and activity logs based on retention settings.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--screenshot-days',
            type=int,
            default=settings.SCREENSHOT_RETENTION_DAYS,
            help='Delete screenshots older than this many days.',
        )
        parser.add_argument(
            '--activity-days',
            type=int,
            default=settings.ACTIVITY_LOG_RETENTION_DAYS,
            help='Delete activity logs older than this many days.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without deleting anything.',
        )

    def handle(self, *args, **options):
        screenshot_days = options['screenshot_days']
        activity_days = options['activity_days']
        dry_run = options['dry_run']

        now = timezone.now()
        screenshot_cutoff = now - timedelta(days=screenshot_days)
        activity_cutoff = now - timedelta(days=activity_days)

        stale_screenshots = Screenshot.objects.filter(captured_at__lt=screenshot_cutoff)
        stale_activity_logs = ActivityLog.objects.filter(created_at__lt=activity_cutoff)

        screenshot_count = stale_screenshots.count()
        activity_count = stale_activity_logs.count()

        self.stdout.write(
            self.style.NOTICE(
                f'Screenshots older than {screenshot_days} days: {screenshot_count}'
            )
        )
        self.stdout.write(
            self.style.NOTICE(
                f'Activity logs older than {activity_days} days: {activity_count}'
            )
        )

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run enabled. No data deleted.'))
            return

        deleted_files = 0
        deleted_screenshot_rows = 0

        for screenshot in stale_screenshots.iterator(chunk_size=500):
            if screenshot.image:
                screenshot.image.delete(save=False)
                deleted_files += 1
            screenshot.delete()
            deleted_screenshot_rows += 1

        deleted_activity_rows = stale_activity_logs.delete()[0]

        self.stdout.write(
            self.style.SUCCESS(
                f'Deleted {deleted_files} screenshot files, '
                f'{deleted_screenshot_rows} screenshot rows, and '
                f'{deleted_activity_rows} activity-related rows.'
            )
        )