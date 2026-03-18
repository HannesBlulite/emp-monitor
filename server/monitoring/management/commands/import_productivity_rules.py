"""
Management command to import productivity rules from CSV or XLSX files.

Usage:
    python manage.py import_productivity_rules "Productivity Rule (1).xlsx"
    python manage.py import_productivity_rules rules.csv --dry-run
    python manage.py import_productivity_rules rules.csv --clear-existing
"""

import csv
import os

from django.core.management.base import BaseCommand, CommandError

from monitoring.models import ProductivityRule


class Command(BaseCommand):
    help = 'Import productivity rules from a CSV or XLSX file.'

    def add_arguments(self, parser):
        parser.add_argument(
            'file',
            type=str,
            help='Path to the CSV or XLSX file to import.',
        )
        parser.add_argument(
            '--clear-existing',
            action='store_true',
            help='Delete all existing rules before importing.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be imported without making changes.',
        )

    def handle(self, *args, **options):
        file_path = options['file']
        dry_run = options['dry_run']
        clear_existing = options['clear_existing']

        if not os.path.isfile(file_path):
            raise CommandError(f'File not found: {file_path}')

        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.xlsx':
            rows = self._read_xlsx(file_path)
        elif ext == '.csv':
            rows = self._read_csv(file_path)
        else:
            raise CommandError(f'Unsupported file type: {ext}. Use .csv or .xlsx')

        # Normalize rows
        rules_to_import = []
        skipped = 0
        for row in rows:
            rule = self._normalize_row(row)
            if rule:
                rules_to_import.append(rule)
            else:
                skipped += 1

        self.stdout.write(
            f'Found {len(rules_to_import)} valid rules '
            f'({skipped} rows skipped)'
        )

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no changes made.'))
            for r in rules_to_import[:20]:
                self.stdout.write(
                    f'  {r["match_type"]:8s} | {r["pattern"]:40s} | {r["category"]}'
                )
            if len(rules_to_import) > 20:
                self.stdout.write(f'  ... and {len(rules_to_import) - 20} more')
            return

        if clear_existing:
            deleted, _ = ProductivityRule.objects.all().delete()
            self.stdout.write(self.style.WARNING(
                f'Deleted {deleted} existing rules.'
            ))

        created = 0
        updated = 0
        for r in rules_to_import:
            obj, was_created = ProductivityRule.objects.update_or_create(
                match_type=r['match_type'],
                pattern=r['pattern'],
                defaults={'category': r['category']},
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done: {created} created, {updated} updated.'
        ))

    def _read_xlsx(self, file_path):
        try:
            import openpyxl
        except ImportError:
            raise CommandError(
                'openpyxl is required for XLSX import. '
                'Install it: pip install openpyxl'
            )

        wb = openpyxl.load_workbook(file_path, read_only=True)
        ws = wb.active
        rows = []
        header = None
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                header = [str(c).strip().lower() if c else '' for c in row]
                continue
            row_dict = {}
            for j, val in enumerate(row):
                if j < len(header):
                    row_dict[header[j]] = val
            rows.append(row_dict)
        wb.close()
        return rows

    def _read_csv(self, file_path):
        rows = []
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Normalize keys to lowercase
                rows.append({k.strip().lower(): v for k, v in row.items()})
        return rows

    def _normalize_row(self, row):
        """
        Normalize a row from the imported file to our model fields.

        Expected columns (case-insensitive):
            Type: 'Website' or 'Application'
            Activity: the domain or app name
            status: 'Productive', 'Unproductive', or 'Neutral'
        """
        raw_type = str(row.get('type', '')).strip().lower()
        pattern = str(row.get('activity', '')).strip()
        raw_status = str(row.get('status', '')).strip().lower()

        if not pattern or not raw_type:
            return None

        # Map type
        if raw_type == 'website':
            match_type = 'domain'
        elif raw_type == 'application':
            match_type = 'app'
        else:
            return None

        # Map status
        category_map = {
            'productive': 'productive',
            'unproductive': 'unproductive',
            'neutral': 'neutral',
        }
        category = category_map.get(raw_status, 'neutral')

        return {
            'match_type': match_type,
            'pattern': pattern.lower(),
            'category': category,
        }
