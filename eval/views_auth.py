from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.shortcuts import redirect, render
from django.contrib.auth import authenticate, login
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm
from django.urls import reverse

# Direct admin login view that bypasses domain restrictions
def admin_login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        # Print debug info (will show in server console)
        print(f'Admin login attempt: username={username}, password_length={len(password) if password else 0}')
        
        # Try to get the user directly first
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        try:
            user = User.objects.get(username=username)
            # Check if password matches directly
            if user.check_password(password):
                # Force login the user
                login(request, user)
                messages.success(request, f'Welcome, {user.username}!')
                return redirect('/')  # Redirect to home page after login
            else:
                print('Password check failed')
                messages.error(request, 'Invalid password. Please try again.')
        except User.DoesNotExist:
            print('User does not exist')
            messages.error(request, 'User does not exist. Please check the username.')
    
    return render(request, 'admin_login.html')

@ensure_csrf_cookie
def direct_admin_page(request):
    """Serve the direct admin login page without any middleware interference"""
    return render(request, 'direct_admin.html')

def direct_admin_auth(request):
    """Direct authentication endpoint for admin users"""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        print(f'Direct admin auth attempt: username={username}, password={password}')
        
        try:
            # Try to get user directly from database
            user = User.objects.get(username=username)
            
            # Verify password directly
            if user.check_password(password):
                # Force login the user with the ModelBackend
                from django.contrib.auth import get_backends
                for backend in get_backends():
                    if isinstance(backend, __import__('django.contrib.auth.backends').contrib.auth.backends.ModelBackend):
                        # Set the backend attribute on the user
                        user.backend = f'{backend.__module__}.{backend.__class__.__name__}'
                        login(request, user)
                        return JsonResponse({'success': True})
                # Fallback if ModelBackend not found
                return JsonResponse({'success': False, 'error': 'Authentication backend not found'})
            else:
                return JsonResponse({'success': False, 'error': 'Invalid password'})
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'User does not exist'})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

class TuringDomainLoginView(LoginView):
    """
    Custom login view that enforces the Turing ID restriction.
    This provides an additional check at login time.
    """
    template_name = 'login.html'
    form_class = AuthenticationForm
    success_url = '/'  # Redirect to the index view (dashboard) after successful login
    
    def get_success_url(self):
        """Return the URL to redirect to after successful login."""
        user = self.request.user
        # Redirect pod_lead users to reviewer_dashboard
        if user.is_authenticated and user.groups.filter(name="pod_lead").exists():
            return reverse('reviewer_dashboard')
        # Redirect trainer users to /dashboard/tasks/
        if user.is_authenticated and user.groups.filter(name="trainer").exists():
            return '/dashboard/tasks/'
        # Default: dashboard/home
        print(f'Redirecting user {user.username} to dashboard')
        return self.success_url
        
    def form_valid(self, form):
        # Get the user from the form
        user = form.get_user()
        
        # Always allow superusers to log in regardless of email domain
        if user and user.is_superuser:
            # Make sure the user has a backend attribute
            if not hasattr(user, 'backend'):
                from django.contrib.auth import get_backends
                for backend in get_backends():
                    if isinstance(backend, __import__('django.contrib.auth.backends').contrib.auth.backends.ModelBackend):
                        user.backend = f'{backend.__module__}.{backend.__class__.__name__}'
                        break
            
            # Debug logging
            print(f'Superuser login: {user.username}')
            print(f'DEBUG: About to login user {user.username}')
            
            # Perform login
            from django.contrib.auth import login
            login(self.request, user)
            
            # More debug logging
            print(f'DEBUG: Login completed for {user.username}')
            print(f'DEBUG: Redirecting to dashboard at /')
            
            # Force direct redirect to dashboard
            from django.shortcuts import redirect
            return redirect('/')
            
        # For non-superusers, check if the email domain is allowed
        if user and user.email:
            # Define allowed domains
            allowed_domains = ['turing.com', 'admin.turing.com', 'lead.turing.com']
            
            # Check if the email domain is allowed
            is_allowed = False
            for domain in allowed_domains:
                if user.email.endswith('@' + domain):
                    is_allowed = True
                    break
            
            # If not allowed, show an error message and redirect back to login
            if not is_allowed:
                messages.error(
                    self.request,
                    'Access denied: Only Official Turing ID is allowed. '
                    'Please sign in with your Official Turing ID.'
                )
                return redirect('login')
        
        # If allowed, proceed with normal login
        return super().form_valid(form)
