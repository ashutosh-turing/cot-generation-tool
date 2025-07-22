import os
from google.cloud import pubsub_v1
from django.conf import settings
import json

# Configure the project and topic
project_id = settings.GOOGLE_CLOUD_PROJECT_ID
topic_id = "v2-cot-llm-requests"

# Create a publisher client for v2-cot-llm-requests
credentials_path = os.path.join(settings.BASE_DIR, 'service_account.json')
llm_publisher = pubsub_v1.PublisherClient.from_service_account_file(credentials_path)
llm_topic_path = llm_publisher.topic_path(project_id, topic_id)

# Create a publisher client for v2-cot-llm-notifications
notification_topic_id = "v2-cot-llm-notifications"
notification_publisher = pubsub_v1.PublisherClient.from_service_account_file(credentials_path)
notification_topic_path = notification_publisher.topic_path(project_id, notification_topic_id)

def publish_message(data):
    """Publishes a message to a Pub/Sub topic."""
    """Publishes a message to the v2-cot-llm-requests topic."""
    try:
        # Data must be a bytestring
        data = json.dumps(data).encode("utf-8")
        future = llm_publisher.publish(llm_topic_path, data)
        print(f"Published message ID: {future.result()}")
        return True
    except Exception as e:
        print(f"Error publishing message: {e}")
        return False

def publish_notification(data):
    """Publishes a notification to the v2-cot-llm-notifications topic."""
    try:
        # Publish to Pub/Sub (notifications are now handled via polling, not WebSocket)
        pubsub_data = json.dumps(data).encode("utf-8")
        future = notification_publisher.publish(notification_topic_path, pubsub_data)
        print(f"Published notification ID: {future.result()}")
        print("Note: Notifications are now handled via polling API, not real-time WebSocket")

    except Exception as e:
        print(f"Error publishing notification: {e}")
