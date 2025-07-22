import os
from django.core.management.base import BaseCommand
from google.cloud import pubsub_v1
from django.conf import settings

class Command(BaseCommand):
    help = 'Sets up the necessary Pub/Sub topics and subscriptions for the application.'

    def handle(self, *args, **options):
        project_id = settings.GOOGLE_CLOUD_PROJECT_ID
        
        # Set the GOOGLE_APPLICATION_CREDENTIALS environment variable
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.SERVICE_ACCOUNT_FILE

        # Create a publisher client
        publisher = pubsub_v1.PublisherClient()

        # Create topics
        topics = ["v2-cot-llm-requests", "v2-cot-llm-notifications"]
        for topic_id in topics:
            topic_path = publisher.topic_path(project_id, topic_id)
            try:
                publisher.create_topic(request={"name": topic_path})
                self.stdout.write(self.style.SUCCESS(f"Topic {topic_id} created."))
            except Exception as e:
                if "already exists" in str(e):
                    self.stdout.write(self.style.WARNING(f"Topic {topic_id} already exists."))
                else:
                    self.stdout.write(self.style.ERROR(f"Error creating topic {topic_id}: {e}"))

        # Create a subscriber client
        subscriber = pubsub_v1.SubscriberClient()

        # Create subscriptions
        subscriptions = {
            "v2-cot-llm-requests-subscription": "v2-cot-llm-requests",
            "v2-cot-llm-notifications-subscription": "v2-cot-llm-notifications"
        }
        for sub_id, topic_id in subscriptions.items():
            subscription_path = subscriber.subscription_path(project_id, sub_id)
            topic_path = publisher.topic_path(project_id, topic_id)
            try:
                subscriber.create_subscription(
                    request={"name": subscription_path, "topic": topic_path}
                )
                self.stdout.write(self.style.SUCCESS(f"Subscription {sub_id} created for topic {topic_id}."))
            except Exception as e:
                if "already exists" in str(e):
                    self.stdout.write(self.style.WARNING(f"Subscription {sub_id} already exists."))
                else:
                    self.stdout.write(self.style.ERROR(f"Error creating subscription {sub_id}: {e}"))
