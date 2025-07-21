from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from allauth.socialaccount.models import SocialAccount

User = get_user_model()

class Command(BaseCommand):
    help = 'Removes all users with non-turing.com email addresses'
    
    def handle(self, *args, **options):
        # Define allowed domains
        allowed_domains = ['turing.com', 'admin.turing.com', 'lead.turing.com']
        
        # Get all users
        users = User.objects.all()
        removed_count = 0
        
        for user in users:
            # Skip superusers
            if user.is_superuser:
                self.stdout.write(self.style.WARNING(f'Skipping superuser: {user.username} ({user.email})'))
                continue
                
            # Check if the user's email domain is allowed
            is_allowed = False
            if user.email:
                for domain in allowed_domains:
                    if user.email.endswith('@' + domain):
                        is_allowed = True
                        break
            
            # If not allowed, remove the user
            if not is_allowed:
                # Get associated social accounts
                social_accounts = SocialAccount.objects.filter(user=user)
                
                # Delete social accounts first
                for account in social_accounts:
                    self.stdout.write(f'Deleting social account: {account.provider} for {user.username}')
                    account.delete()
                
                # Delete the user
                self.stdout.write(f'Deleting user: {user.username} ({user.email})')
                user.delete()
                removed_count += 1
        
        self.stdout.write(self.style.SUCCESS(f'Successfully removed {removed_count} users with non-turing.com emails'))
