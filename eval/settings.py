import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add or update these settings
ALLOWED_HOSTS = ['*']  # For development only
USE_X_FORWARDED_HOST = True
CSRF_TRUSTED_ORIGINS = ['http://localhost:8000']

# Uniform API endpoint settings from .env
DEEPSEEK_API_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com")
FIREWORKS_API_URL = os.environ.get("FIREWORKS_API_URL", "https://api.fireworks.ai/inference/v1/chat/completions")
OPENAI_API_URL = os.environ.get("OPENAI_API_URL", "https://api.openai.com/v1")

# Ensure you have the required middleware
MIDDLEWARE = [
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
