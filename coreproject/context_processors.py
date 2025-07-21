from eval.models import StreamAndSubject, UserPreference

def streams_and_subjects(request):
    context = {
        'streams_and_subjects': StreamAndSubject.objects.all().order_by('name')
    }
    if request.user.is_authenticated:
        try:
            prefs = request.user.preference
            context['preferred_streams'] = list(prefs.streams_and_subjects.values_list('id', flat=True))
        except UserPreference.DoesNotExist:
            context['preferred_streams'] = []
    else:
        context['preferred_streams'] = []
    return context

def user_group(request):
    """
    Adds 'user_group' to context: 'admin', 'pod_lead', 'trainer', or None.
    """
    group = None
    if request.user.is_authenticated:
        if request.user.is_superuser or request.user.is_staff:
            group = 'admin'
        else:
            user_groups = list(request.user.groups.values_list('name', flat=True))
            if 'pod_lead' in user_groups:
                group = 'pod_lead'
            elif 'trainer' in user_groups:
                group = 'trainer'
    return {'user_group': group}

def websocket_url(request):
    """
    Adds 'WEBSOCKET_URL' to context.
    """
    if request.is_secure():
        protocol = 'wss'
    else:
        protocol = 'ws'
    
    host = request.get_host()
    
    # In production, the WebSocket server might be on a different port or host
    # For now, we'll assume it's on the same host with a different port
    if 'localhost' in host or '127.0.0.1' in host:
        ws_host = 'localhost:8766'
    else:
        # In a real production environment, this would be the actual WebSocket host
        ws_host = host.split(':')[0] + ':8766'
        
    return {'WEBSOCKET_URL': f'{protocol}://{ws_host}'}
