from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()

class TuringDomainBackend(ModelBackend):
    """
    Custom authentication backend that only allows users with turing.com email domains.
    This provides an additional layer of security beyond the social account adapter.
    """
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        # First, try to authenticate with the parent class
        user = super().authenticate(request, username=username, password=password, **kwargs)
        
        # If authentication succeeded, check the email domain
        if user is not None and user.email:
            # Define allowed domains
            allowed_domains = ['turing.com', 'admin.turing.com', 'lead.turing.com']
            
            # Check if the email domain is allowed
            is_allowed = False
            for domain in allowed_domains:
                if user.email.endswith('@' + domain):
                    is_allowed = True
                    break
            
            # If not allowed, reject the authentication
            if not is_allowed:
                return None
        
        return user
