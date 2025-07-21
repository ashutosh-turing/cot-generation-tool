from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth.models import Group
from django.conf import settings
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.contrib import messages

class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def get_callback_url(self, request, app):
        """Override to handle the callback URL issue with 0.0.0.0"""
        callback_url = getattr(settings, 'SOCIALACCOUNT_CALLBACK_URL', None)
        if callback_url:
            return callback_url
        return super().get_callback_url(request, app)
        
    def pre_social_login(self, request, sociallogin):
        """
        Invoked just after a user successfully authenticates via a social provider,
        but before the login is actually processed.
        
        We use this to check if the email domain is allowed.
        """
        # Get the email from the sociallogin object
        email = sociallogin.account.extra_data.get('email', '')
        
        # For debugging - log the email being used
        print(f'Social login attempt with email: {email}')
        
        # Define allowed domains
        allowed_domains = ['turing.com', 'admin.turing.com', 'lead.turing.com']
        
        # Skip check for superusers
        if sociallogin.user and sociallogin.user.is_superuser:
            return
            
        # Check if the email domain is allowed
        is_allowed = False
        for domain in allowed_domains:
            if email.endswith('@' + domain):
                is_allowed = True
                break
        
        # If not allowed, reject the login
        if not is_allowed:
            messages.error(
                request,
                'Access denied: Only Official Turing ID is allowed. '
                'Please sign in with your Official Turing ID.'
            )
            # We need to return a response to prevent the login
            return HttpResponseRedirect(reverse('login'))
            
    def save_user(self, request, sociallogin, form=None):
        """
        This is called when a new user is created via social authentication.
        We'll use this to assign the user to the appropriate group.
        """
        # First, let the default adapter create the user
        user = super().save_user(request, sociallogin, form)
        
        # Get the email domain to determine user type
        email = sociallogin.account.extra_data.get('email', '')
        
        # Get or create the groups
        trainer_group, _ = Group.objects.get_or_create(name='trainer')
        pod_lead_group, _ = Group.objects.get_or_create(name='pod_lead')
        admin_group, _ = Group.objects.get_or_create(name='admin')
        
        # Assign user to appropriate group based on email domain
        if email.endswith('@admin.turing.com'):
            admin_group.user_set.add(user)
        elif email.endswith('@lead.turing.com'):
            pod_lead_group.user_set.add(user)
        elif email.endswith('@turing.com'):
            # Only add to trainer group if it's a turing.com email
            trainer_group.user_set.add(user)
        else:
            # This shouldn't happen due to pre_social_login check, but just in case
            # Don't assign any group for non-turing.com emails
            pass
            
        return user
