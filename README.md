# Prompt Evaluation Project

## Overview
This project is a Django-based web application designed for evaluating and testing AI prompts across different models and APIs, including OpenAI, Fireworks AI, and Google APIs.

## Requirements
- Python 3.12+
- Django 5.1.5
- Various API integrations (see requirements.txt)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/prompt_eval.git
cd prompt_eval
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
Create a `.env` file in the project root with the following variables:
```

DEBUG=True
# API keys for external services
OPENAI_API_KEY=<Add your Key>
DEEPSEEK_API_KEY=<Add your Key>
FIREWORKS_API=<Add your Key>

# Model endpoint URLs for uniformity
DEEPSEEK_API_URL=https://api.deepseek.com
FIREWORKS_API_URL=https://api.fireworks.ai/inference/v1/chat/completions

# OpenAI API endpoint (default)
OPENAI_API_URL=https://api.openai.com/v1

Create Cache folder for Convert_to_json Endpoint
mkdir ./eval/static/converted_jsons
```

5. Run migrations:
```bash
python manage.py migrate
```

6. Start the development server:
```bash
python manage.py runserver
```

## Important Functionality

### API Integrations
- **OpenAI Integration**: Leverage OpenAI's models for prompt testing and evaluation
- **Fireworks AI**: Alternative AI model provider for comparative testing
- **Google APIs**: Integration with Google services for additional functionality

### Key Features
- Prompt testing across multiple AI models
- Performance comparison between different AI providers
- Response evaluation metrics
- User management system
- Export and sharing of results

## Usage Examples

### Example 1: Testing a Prompt with OpenAI
```python
from openai import OpenAI

client = OpenAI()
response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Write a short poem about AI"}]
)
print(response.choices[0].message.content)
```

### Example 2: Comparing with Fireworks AI
```python
from fireworks_ai import Fireworks

client = Fireworks()
response = client.chat.completions.create(
    model="fireworks/models/mixtral-8x7b",
    messages=[{"role": "user", "content": "Write a short poem about AI"}]
)
print(response.choices[0].message.content)
```

### Example 3: Using the Django Admin Interface
1. Create a superuser: `python manage.py createsuperuser`
2. Access the admin interface at `http://localhost:8000/admin/`
3. Create and manage prompts, evaluations, and results

## Deployment
The application is configured to be deployed with Gunicorn and can be served behind Nginx or similar web servers.

For production deployment:
```bash
gunicorn coreproject.wsgi:application --bind 0.0.0.0:8000
```

## Contributing
Contributions are welcome! Please feel free to submit a Pull Request.

## License
This project is exclusively licensed with [Turing.com](https://turing.com). 
This is NOT an Apache 2.0 licensed project.
