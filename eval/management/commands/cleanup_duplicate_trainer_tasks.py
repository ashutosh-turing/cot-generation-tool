from django.core.management.base import BaseCommand
from django.db.models import Count
from eval.models import TrainerTask
from django.utils import timezone


class Command(BaseCommand):
    help = 'Identify and optionally clean up duplicate TrainerTask records'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show duplicates without deleting them',
        )
        parser.add_argument(
            '--field',
            type=str,
            default='question_id',
            help='Field to check for duplicates (default: question_id)',
        )
        parser.add_argument(
            '--project',
            type=str,
            help='Filter by project code (optional)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        field = options['field']
        project_code = options['project']

        self.stdout.write(f"Checking for duplicate TrainerTask records by field: {field}")
        
        # Build the base queryset
        queryset = TrainerTask.objects.all()
        if project_code:
            queryset = queryset.filter(project__code=project_code)
            self.stdout.write(f"Filtering by project: {project_code}")

        # Find duplicates
        duplicates = (
            queryset
            .values(field)
            .annotate(count=Count('id'))
            .filter(count__gt=1)
            .order_by('-count')
        )

        if not duplicates:
            self.stdout.write(
                self.style.SUCCESS(f"No duplicate records found for field '{field}'")
            )
            return

        self.stdout.write(
            self.style.WARNING(f"Found {duplicates.count()} duplicate values for field '{field}':")
        )

        total_duplicates_to_remove = 0
        
        for duplicate in duplicates:
            field_value = duplicate[field]
            count = duplicate['count']
            
            self.stdout.write(f"\n{field}='{field_value}': {count} records")
            
            # Get all records with this duplicate value
            duplicate_records = queryset.filter(**{field: field_value}).order_by('created_at')
            
            # Show details of each duplicate record
            for i, record in enumerate(duplicate_records):
                status = "KEEP (oldest)" if i == 0 else "REMOVE"
                self.stdout.write(
                    f"  ID: {record.id}, Created: {record.created_at}, "
                    f"Updated: {record.updated_at}, Project: {record.project}, "
                    f"Status: {status}"
                )
            
            # Count records that would be removed (all except the first/oldest)
            records_to_remove = count - 1
            total_duplicates_to_remove += records_to_remove
            
            if not dry_run:
                # Keep the oldest record, remove the rest
                records_to_delete = duplicate_records[1:]  # Skip the first (oldest) record
                deleted_count = 0
                for record in records_to_delete:
                    self.stdout.write(f"    Deleting record ID: {record.id}")
                    record.delete()
                    deleted_count += 1
                
                self.stdout.write(
                    self.style.SUCCESS(f"  Deleted {deleted_count} duplicate records")
                )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDRY RUN: Would remove {total_duplicates_to_remove} duplicate records"
                )
            )
            self.stdout.write("Run without --dry-run to actually delete duplicates")
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nCleaned up {total_duplicates_to_remove} duplicate records"
                )
            )

        # Show summary statistics
        self.stdout.write("\n" + "="*50)
        self.stdout.write("SUMMARY:")
        
        remaining_records = queryset.count()
        unique_values = queryset.values(field).distinct().count()
        
        self.stdout.write(f"Total records: {remaining_records}")
        self.stdout.write(f"Unique {field} values: {unique_values}")
        
        if remaining_records != unique_values:
            self.stdout.write(
                self.style.WARNING(
                    f"Still have {remaining_records - unique_values} potential duplicates"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("All records now have unique values!")
            )
