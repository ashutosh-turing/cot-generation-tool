from django.db.models.signals import post_save
from django.contrib.auth.models import User, Group
from django.dispatch import receiver

@receiver(post_save, sender=User)
def add_user_to_trainer_group(sender, instance, created, **kwargs):
    """
    Add all newly created users to the 'trainer' group by default.
    """
    if created:
        group, _ = Group.objects.get_or_create(name='trainer')
        instance.groups.add(group)
