from django.core.management.base import BaseCommand
from eval.models import LLMModel

class Command(BaseCommand):
    help = 'Seeds the database with default LLM models.'

    def handle(self, *args, **options):
        self.stdout.write('Seeding LLM models...')
        
        models_to_seed = [
            {'id': 1, 'name': 'gpt-3.5-turbo', 'provider': 'OpenAI', 'is_active': True},
            {'id': 2, 'name': 'gpt-4', 'provider': 'OpenAI', 'is_active': True},
            {'id': 3, 'name': 'claude-3-opus-20240229', 'provider': 'Anthropic', 'is_active': True},
            {'id': 4, 'name': 'claude-3-sonnet-20240229', 'provider': 'Anthropic', 'is_active': True},
        ]
        
        for model_data in models_to_seed:
            model, created = LLMModel.objects.update_or_create(
                id=model_data['id'],
                defaults=model_data
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Successfully created model: {model.name}'))
            else:
                self.stdout.write(self.style.WARNING(f'Model already exists: {model.name}'))

        self.stdout.write(self.style.SUCCESS('LLM models seeded successfully.'))
