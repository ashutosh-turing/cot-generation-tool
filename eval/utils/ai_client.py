import os
from openai import OpenAI
import anthropic
import google.generativeai as genai
from django.conf import settings

class BaseAIClient:
    def __init__(self, api_key, model_name):
        self.api_key = api_key
        self.model_name = model_name

    def get_response(self, messages, temperature=None):
        raise NotImplementedError("Subclasses must implement this method.")

    def cleanup(self):
        pass

class OpenAIClient(BaseAIClient):
    def __init__(self, api_key, model_name, base_url=None):
        super().__init__(api_key, model_name)
        self.client = OpenAI(api_key=self.api_key, base_url=base_url)

    def get_response(self, messages, temperature=None):
        params = {
            "model": self.model_name,
            "messages": messages,
            "stream": False
        }
        if temperature is not None:
            params["temperature"] = temperature

        response = self.client.chat.completions.create(**params)
        return {
            'status': 'success',
            'response': response.choices[0].message.content,
            'raw_response': response
        }

class AnthropicClient(BaseAIClient):
    def __init__(self, api_key, model_name):
        super().__init__(api_key, model_name)
        self.client = anthropic.Anthropic(api_key=self.api_key)

    def get_response(self, messages, temperature=None):
        # Anthropic's API requires the system message to be passed separately
        system_message = ""
        if messages and messages[0]['role'] == 'system':
            system_message = messages[0]['content']
            messages = messages[1:]

        params = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": 4096  # Recommended default
        }
        if system_message:
            params["system"] = system_message
        if temperature is not None:
            params["temperature"] = temperature

        response = self.client.messages.create(**params)
        return {
            'status': 'success',
            'response': response.content[0].text,
            'raw_response': response
        }

class GeminiClient(BaseAIClient):
    def __init__(self, api_key, model_name):
        super().__init__(api_key, model_name)
        # Use the API key from the database (passed as parameter) or fallback to settings
        api_key_to_use = self.api_key if self.api_key else getattr(settings, 'GOOGLE_API_KEY', None)
        if not api_key_to_use:
            raise ValueError("No API key provided for Gemini model. Please set the API key in the LLMModel database record or in GOOGLE_API_KEY setting.")
        genai.configure(api_key=api_key_to_use)
        self.client = genai.GenerativeModel(self.model_name)

    def get_response(self, messages, temperature=None):
        # Gemini's API has a different structure for messages
        gemini_messages = [msg['content'] for msg in messages if msg['role'] != 'system']
        
        generation_config = {}
        if temperature is not None:
            generation_config["temperature"] = temperature

        response = self.client.generate_content(gemini_messages, generation_config=generation_config)
        return {
            'status': 'success',
            'response': response.text,
            'raw_response': response
        }

def get_ai_client(provider, api_key, model_name):
    provider = provider.lower()
    if provider == 'openai':
        return OpenAIClient(api_key, model_name)
    elif provider == 'anthropic':
        return AnthropicClient(api_key, model_name)
    elif provider == 'gemini':
        return GeminiClient(api_key, model_name)
    else:
        raise ValueError(f"Unsupported AI provider: {provider}")
