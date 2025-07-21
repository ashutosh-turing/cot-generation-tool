from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('eval', '0004_systemmessage'),  # Updated to depend on the latest migration
    ]

    operations = [
        migrations.AddField(
            model_name='modelevaluationhistory',
            name='is_edited',
            field=models.BooleanField(default=False),
        ),
    ]
