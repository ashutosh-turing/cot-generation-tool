import os

# Removed dotenv and .env dependency. All config should be fetched from DB or hardcoded as needed.

# Add or update these settings
ALLOWED_HOSTS = ['*']  # For development only
USE_X_FORWARDED_HOST = True
CSRF_TRUSTED_ORIGINS = ['http://localhost:8000']

# Ensure you have the required middleware
MIDDLEWARE = [
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Pub/Sub topic and subscription names (configurable via environment variables)
PUBSUB_TOPIC_LLM_REQUESTS = os.environ.get("PUBSUB_TOPIC_LLM_REQUESTS", "v2-cot-llm-requests")
PUBSUB_TOPIC_LLM_NOTIFICATIONS = os.environ.get("PUBSUB_TOPIC_LLM_NOTIFICATIONS", "v2-cot-llm-notifications")
PUBSUB_SUB_LLM_REQUESTS = os.environ.get("PUBSUB_SUB_LLM_REQUESTS", "v2-cot-llm-requests-subscription")
PUBSUB_SUB_LLM_NOTIFICATIONS = os.environ.get("PUBSUB_SUB_LLM_NOTIFICATIONS", "v2-cot-llm-notifications-subscription")
