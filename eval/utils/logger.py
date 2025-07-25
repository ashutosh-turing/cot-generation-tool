from django.conf import settings

def log(*args, **kwargs):
    if getattr(settings, 'DEBUG', False):
        print(*args, **kwargs)