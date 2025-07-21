from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse
from django.contrib.auth import logout

class TuringDomainMiddleware:
    """
    Middleware to enforce turing.com email domain restriction on every request.
    This provides a final layer of protection to ensure only authorized users can access the system.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        # Define allowed domains once at initialization
        self.allowed_domains = ['turing.com', 'admin.turing.com', 'lead.turing.com']
        # Define paths that should always be accessible
        self.public_paths = [
            '/accounts/',  # All auth URLs
            '/admin/',    # Admin URLs
            '/static/',   # Static files
        ]
        
    def __call__(self, request):
        # First check if this is a public path that should always be accessible
        for path in self.public_paths:
            if request.path.startswith(path):
                return self.get_response(request)
                
        # Check authenticated users
        if request.user.is_authenticated:
            # Skip check for superusers
            if request.user.is_superuser:
                return self.get_response(request)
                
            # Check if the user's email domain is allowed
            user_email = request.user.email
            is_allowed = False
            
            if user_email:  # Make sure email exists
                for domain in self.allowed_domains:
                    if user_email.endswith('@' + domain):
                        is_allowed = True
                        break
            
            # If not allowed, force logout and redirect to login page
            if not is_allowed:
                # Add error message
                messages.error(
                    request,
                    'Access restricted: Only Official Turing ID is allowed. '
                    'You have been logged out for security reasons.'
                )
                # Log the user out
                logout(request)
                # Delete any session data
                request.session.flush()
                # Redirect to login page
                return redirect(reverse('login'))
        
        # For non-authenticated users trying to access protected URLs, redirect to login
        else:
            # Redirect to login page for protected URLs
            return redirect(reverse('login'))
            
        # Continue with the request for allowed users
        return self.get_response(request)
