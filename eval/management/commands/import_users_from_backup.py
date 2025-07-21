from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
import os
from processor.utils import import_users_from_backup, log_message

class Command(BaseCommand):
    help = 'Imports users and their permissions from a backup SQLite database'

    def add_arguments(self, parser):
        parser.add_argument(
            'backup_path',
            type=str,
            help='Path to the backup SQLite database file',
        )

    def handle(self, *args, **options):
        backup_path = options['backup_path']
        
        # Check if the backup file exists
        if not os.path.exists(backup_path):
            raise CommandError(f'Backup file not found at {backup_path}')
        
        self.stdout.write(f'Importing users from {backup_path}...')
        
        # Call the utility function to import users
        success, message = import_users_from_backup(backup_path)
        
        if success:
            self.stdout.write(self.style.SUCCESS(message))
        else:
            raise CommandError(message)