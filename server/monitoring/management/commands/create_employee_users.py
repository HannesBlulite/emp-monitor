"""
Management command to create Django user accounts for employees.

For each Employee without a linked User, creates a User with:
- username: first name lowercase (e.g. 'danita')
- password: first name + '2026' (e.g. 'danita2026')
- is_staff: False (no admin access)

Usage:
    python manage.py create_employee_users
    python manage.py create_employee_users --exclude hannes
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from monitoring.models import Employee


class Command(BaseCommand):
    help = 'Create Django user accounts for employees that do not have one.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--exclude',
            nargs='*',
            default=[],
            help='Display names to exclude (case-insensitive), e.g. --exclude hannes',
        )
        parser.add_argument(
            '--password-suffix',
            default='2026',
            help='Suffix appended to first-name password (default: 2026)',
        )

    def handle(self, *args, **options):
        exclude_names = [n.lower() for n in options['exclude']]
        suffix = options['password_suffix']

        employees = Employee.objects.filter(user__isnull=True, is_active=True)
        created = 0
        skipped = 0

        for emp in employees:
            if emp.display_name.lower() in exclude_names:
                self.stdout.write(f'  Skipped (excluded): {emp.display_name}')
                skipped += 1
                continue

            # Generate username from first name
            first_name = emp.display_name.split()[0].lower()
            username = first_name

            # Ensure unique username
            base = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f'{base}{counter}'
                counter += 1

            # Create the user (is_staff=False, is_superuser=False)
            password = f'{first_name}{suffix}'
            user = User.objects.create_user(
                username=username,
                password=password,
                first_name=emp.display_name.split()[0].title(),
                last_name=' '.join(emp.display_name.split()[1:]).title() if len(emp.display_name.split()) > 1 else '',
                is_staff=False,
                is_superuser=False,
            )

            # Link to employee
            emp.user = user
            emp.save(update_fields=['user'])

            self.stdout.write(
                self.style.SUCCESS(
                    f'  Created: {emp.display_name} -> username="{username}", password="{password}"'
                )
            )
            created += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Done. Created {created} accounts, skipped {skipped}.'))
        if created > 0:
            self.stdout.write(self.style.WARNING(
                'Staff should change their passwords after first login.'
            ))
