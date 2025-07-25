import os
import re
import time
from openai import OpenAI
import anthropic
import google.generativeai as genai
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class BaseAIClient:
    def __init__(self, api_key, model_name, model_instance=None):
        self.api_key = api_key
        self.model_name = model_name
        self.model_instance = model_instance

    def get_response(self, messages, temperature=None, max_tokens=None):
        """Universal response method with transparent streaming support."""
        if self._should_use_streaming():
            return self._get_response_with_streaming(messages, temperature, max_tokens)
        else:
            return self._get_response_without_streaming(messages, temperature, max_tokens)

    def _should_use_streaming(self):
        """Determine if streaming should be used based on configuration and smart defaults."""
        # 1. Check explicit configuration from database
        if hasattr(self.model_instance, 'use_streaming') and self.model_instance.use_streaming is not None:
            return self.model_instance.use_streaming
        
        # 2. Smart defaults based on token requirements
        effective_tokens = self._get_effective_max_tokens()
        if effective_tokens > 8000:
            return True  # Always stream for high token requests
        
        # 3. Provider-specific smart defaults
        provider = getattr(self, 'provider', '').lower()
        if provider == 'anthropic':
            return True  # Anthropic benefits most from streaming
        elif provider == 'openai':
            return True  # OpenAI also supports streaming well
        elif provider == 'gemini':
            return True  # Gemini supports streaming
        
        return False  # Default to streaming for reliability

    def _get_effective_max_tokens(self):
        """Get the effective max_tokens that will be used."""
        if self.model_instance and self.model_instance.max_tokens:
            return self.model_instance.max_tokens
        return self._get_default_max_tokens()

    def _get_default_max_tokens(self):
        """Get default max_tokens - to be implemented by subclasses."""
        return 4096  # Conservative default

    def _get_response_with_streaming(self, messages, temperature=None, max_tokens=None):
        """Universal streaming collection that works for all providers."""
        full_response = ""
        chunk_count = 0
        
        try:
            logger.info(f"Starting streaming response for {self.model_name}")
            
            for chunk in self._stream_response(messages, temperature, max_tokens):
                if chunk:  # Only add non-empty chunks
                    full_response += chunk
                    chunk_count += 1
            
            logger.info(f"Streaming completed: {len(full_response)} chars, {chunk_count} chunks")
            
            return {
                'status': 'success',
                'response': full_response,
                'raw_response': None,  # Streaming doesn't have single raw response
                'completion_attempts': 1,
                'was_continued': False,
                'used_streaming': True,
                'chunk_count': chunk_count
            }
            
        except NotImplementedError:
            logger.info("Streaming not implemented for this provider, using non-streaming")
            return self._get_response_without_streaming(messages, temperature, max_tokens)
        except Exception as e:
            logger.warning(f"Streaming failed: {e}, falling back to non-streaming")
            return self._get_response_without_streaming(messages, temperature, max_tokens)

    def _get_response_without_streaming(self, messages, temperature=None, max_tokens=None):
        """Fallback to non-streaming response - to be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement non-streaming response method.")

    def _stream_response(self, messages, temperature=None, max_tokens=None):
        """Provider-specific streaming implementation - to be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement streaming method.")

    def cleanup(self):
        pass

class OpenAIClient(BaseAIClient):
    def __init__(self, api_key, model_name, model_instance=None, base_url=None):
        super().__init__(api_key, model_name, model_instance)
        self.client = OpenAI(api_key=self.api_key, base_url=base_url)
        self.provider = 'openai'

    def _get_default_max_tokens(self):
        """Get default max_tokens for OpenAI models."""
        model_lower = self.model_name.lower()
        if 'gpt-4' in model_lower:
            if 'turbo' in model_lower or '1106' in model_lower or '0125' in model_lower:
                return 4096  # GPT-4 Turbo models
            else:
                return 8192  # GPT-4 base model
        elif 'gpt-3.5' in model_lower:
            return 4096  # GPT-3.5 Turbo
        else:
            return 4096  # Conservative default

    def _stream_response(self, messages, temperature=None, max_tokens=None):
        """OpenAI streaming implementation."""
        params = {
            "model": self.model_name,
            "messages": messages,
            "stream": True
        }
        
        # Use max_tokens parameter if provided, else fall back to model_instance or default
        if max_tokens is not None:
            if 'o4-mini'in self.model_name:
                params["max_completion_tokens"] = max_tokens
            else:
                params["max_tokens"] = max_tokens
        elif self.model_instance and self.model_instance.max_tokens:
            params["max_tokens"] = self.model_instance.max_tokens
        else:
            params["max_tokens"] = self._get_default_max_tokens()
            
        if temperature is not None and 'o4-mini'not in self.model_name:
            params["temperature"] = temperature

        try:
            response = self.client.chat.completions.create(**params)
            for chunk in response:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"OpenAI streaming error: {e}")
            raise

    def _get_response_without_streaming(self, messages, temperature=None, max_tokens=None):
        """OpenAI non-streaming fallback implementation."""
        params = {
            "model": self.model_name,
            "messages": messages,
            "stream": False
        }
        
        # Use max_tokens parameter if provided, else fall back to model_instance or default
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        elif self.model_instance and self.model_instance.max_tokens:
            params["max_tokens"] = self.model_instance.max_tokens
            
        if temperature is not None:
            params["temperature"] = temperature

        try:
            response = self.client.chat.completions.create(**params)
            return {
                'status': 'success',
                'response': response.choices[0].message.content,
                'raw_response': response,
                'completion_attempts': 1,
                'was_continued': False,
                'used_streaming': False
            }
        except Exception as e:
            logger.error(f"OpenAI non-streaming error: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'response': '',
                'completion_attempts': 1,
                'was_continued': False,
                'used_streaming': False
            }

class AnthropicClient(BaseAIClient):
    def __init__(self, api_key, model_name, model_instance=None):
        super().__init__(api_key, model_name, model_instance)
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.provider = 'anthropic'

    def _get_default_max_tokens(self):
        """Get full max_tokens capacity with streaming support."""
        model_lower = self.model_name.lower()
        # Match Claude Sonnet 4 with any date suffix (e.g., claude-sonnet-4-20250514)
        if ('claude-sonnet-4' in model_lower or 'sonnet-4' in model_lower or 
            'claude-4-sonnet' in model_lower or '4-sonnet' in model_lower):
            logger.info(f"Detected Claude Sonnet 4 model: {self.model_name}, using 64K tokens")
            return 64000  # Claude Sonnet 4: Full capacity with streaming
        elif 'sonnet' in model_lower:
            return 8192   # Claude 3.5 Sonnet full capacity
        elif 'haiku' in model_lower:
            return 4096   # Claude 3 Haiku full capacity
        elif 'opus' in model_lower:
            return 4096   # Claude 3 Opus full capacity
        else:
            return 8192   # Conservative default for unknown models

    def _stream_response(self, messages, temperature=None, max_tokens=None):
        """Anthropic streaming implementation."""
        # Anthropic's API requires the system message to be passed separately
        system_message = ""
        if messages and messages[0]['role'] == 'system':
            system_message = messages[0]['content']
            messages = messages[1:]

        # Use max_tokens parameter if provided, else fall back to model_instance or default
        if max_tokens is not None:
            effective_max_tokens = max_tokens
        elif self.model_instance and self.model_instance.max_tokens:
            effective_max_tokens = self.model_instance.max_tokens
        else:
            effective_max_tokens = self._get_default_max_tokens()
        
        params = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": effective_max_tokens
        }
        
        if system_message:
            params["system"] = system_message
        if temperature is not None:
            params["temperature"] = temperature

        try:
            # Anthropic streaming API - no 'stream' parameter needed
            with self.client.messages.stream(**params) as stream:
                for chunk in stream:
                    if chunk.type == "content_block_delta":
                        yield chunk.delta.text
        except Exception as e:
            logger.error(f"Anthropic streaming error: {e}")
            raise

    def _get_response_without_streaming(self, messages, temperature=None, max_tokens=None):
        """Anthropic non-streaming fallback with continuation logic."""
        return self._get_response_with_continuation(messages, temperature, max_tokens=max_tokens)

    def _get_response_with_continuation(self, messages, temperature=None, max_retries=3, max_tokens=None):
        """Original continuation-based approach as fallback."""
        # Anthropic's API requires the system message to be passed separately
        system_message = ""
        if messages and messages[0]['role'] == 'system':
            system_message = messages[0]['content']
            messages = messages[1:]

        # Use max_tokens parameter if provided, else fall back to model_instance or default
        if max_tokens is not None:
            effective_max_tokens = min(max_tokens, 16000)  # Cap at 16K for non-streaming
        elif self.model_instance and self.model_instance.max_tokens:
            effective_max_tokens = min(self.model_instance.max_tokens, 16000)
        else:
            # Conservative limits for non-streaming with improved model detection
            model_lower = self.model_name.lower()
            if ('claude-sonnet-4' in model_lower or 'sonnet-4' in model_lower or 
                'claude-4-sonnet' in model_lower or '4-sonnet' in model_lower):
                effective_max_tokens = 16000  # Conservative for non-streaming Claude Sonnet 4
                logger.info(f"Using conservative 16K tokens for non-streaming Claude Sonnet 4: {self.model_name}")
            elif 'sonnet' in model_lower:
                effective_max_tokens = 8192
            elif 'haiku' in model_lower:
                effective_max_tokens = 4096
            elif 'opus' in model_lower:
                effective_max_tokens = 4096
            else:
                effective_max_tokens = 8192
        
        params = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": effective_max_tokens
        }
        
        if system_message:
            params["system"] = system_message
        if temperature is not None:
            params["temperature"] = temperature

        try:
            # Initial API call
            response = self.client.messages.create(**params)
            initial_response = response.content[0].text
            
            logger.info(f"Initial non-streaming response length: {len(initial_response)} chars")
            
            # Check if response is complete
            if not self._is_response_incomplete(initial_response):
                logger.info("Non-streaming response appears complete")
                return {
                    'status': 'success',
                    'response': initial_response,
                    'raw_response': response,
                    'completion_attempts': 1,
                    'was_continued': False,
                    'used_streaming': False
                }
            
            # Response appears incomplete, attempt continuation
            logger.warning("Non-streaming response incomplete, attempting continuation...")
            combined_response = initial_response
            continuation_attempts = 0
            
            for attempt in range(max_retries):
                continuation_attempts += 1
                logger.info(f"Continuation attempt {continuation_attempts}/{max_retries}")
                
                # Create continuation prompt
                continuation_messages = self._create_continuation_prompt(messages, combined_response)
                
                # Prepare continuation parameters
                continuation_params = params.copy()
                continuation_params["messages"] = continuation_messages
                
                try:
                    # Wait a bit to avoid rate limiting
                    time.sleep(1)
                    
                    # Make continuation API call
                    continuation_response = self.client.messages.create(**continuation_params)
                    continuation_text = continuation_response.content[0].text
                    
                    logger.info(f"Continuation {continuation_attempts} length: {len(continuation_text)} chars")
                    
                    # Combine responses intelligently
                    if continuation_text.strip():
                        # Remove any repetition from the beginning of continuation
                        continuation_clean = self._clean_continuation_text(combined_response, continuation_text)
                        combined_response = combined_response + "\n\n" + continuation_clean
                        
                        # Check if this continuation completes the response
                        if not self._is_response_incomplete(continuation_clean):
                            logger.info(f"Response completed after {continuation_attempts} continuation(s)")
                            return {
                                'status': 'success',
                                'response': combined_response,
                                'raw_response': response,
                                'completion_attempts': continuation_attempts + 1,
                                'was_continued': True,
                                'used_streaming': False
                            }
                    else:
                        logger.warning(f"Empty continuation response on attempt {continuation_attempts}")
                        break
                        
                except Exception as e:
                    logger.error(f"Error in continuation attempt {continuation_attempts}: {e}")
                    break
            
            # Return combined response even if not fully complete
            logger.warning(f"Returning potentially incomplete response after {continuation_attempts} attempts")
            return {
                'status': 'success',
                'response': combined_response,
                'raw_response': response,
                'completion_attempts': continuation_attempts + 1,
                'was_continued': True,
                'used_streaming': False,
                'warning': 'Response may still be incomplete after maximum retry attempts'
            }
            
        except Exception as e:
            logger.error(f"Error in Anthropic non-streaming call: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'response': '',
                'completion_attempts': 1,
                'was_continued': False,
                'used_streaming': False
            }

    def _is_response_incomplete(self, response_text):
        """
        Detect if a response appears to be incomplete or truncated.
        
        Args:
            response_text (str): The response text to analyze
            
        Returns:
            bool: True if response appears incomplete
        """
        if not response_text or not response_text.strip():
            return True
            
        response_text = response_text.strip()
        
        # Check for common truncation indicators
        truncation_indicators = [
            # Incomplete sentences
            r'[a-zA-Z0-9]\s*$',  # Ends with alphanumeric character (no punctuation)
            # Incomplete code blocks
            r'```[^`]*$',  # Unclosed code block
            # Incomplete analysis sections
            r'(Analysis|Review|Check|Summary|Conclusion):\s*$',  # Section header with no content
            # Incomplete lists
            r'\d+\.\s*$',  # Numbered list item with no content
            r'[-*]\s*$',   # Bullet point with no content
            # Incomplete explanations
            r'(because|since|therefore|however|moreover|furthermore|additionally)\s*$',
            # Incomplete code or technical content
            r'(function|class|def|if|for|while|try)\s*$',
        ]
        
        for pattern in truncation_indicators:
            if re.search(pattern, response_text, re.IGNORECASE | re.MULTILINE):
                logger.warning(f"Detected potential truncation with pattern: {pattern}")
                return True
        
        # Check for very short responses that seem incomplete for analysis tasks
        if len(response_text) < 50:
            logger.warning(f"Response too short ({len(response_text)} chars), likely incomplete")
            return True
            
        # Check for incomplete sentences (no ending punctuation in last 100 chars)
        last_part = response_text[-100:].strip()
        if last_part and not re.search(r'[.!?;}\])]$', last_part):
            logger.warning("Response doesn't end with proper punctuation, likely incomplete")
            return True
            
        return False

    def _create_continuation_prompt(self, original_messages, partial_response):
        """
        Create a continuation prompt to complete an incomplete response.
        
        Args:
            original_messages (list): Original conversation messages
            partial_response (str): The incomplete response received
            
        Returns:
            list: Updated messages for continuation
        """
        # Create continuation messages
        continuation_messages = original_messages.copy()
        
        # Add the partial response as an assistant message
        continuation_messages.append({
            "role": "assistant", 
            "content": partial_response
        })
        
        # Add continuation prompt
        continuation_messages.append({
            "role": "user",
            "content": "Please continue your previous response from where you left off. Complete the analysis or explanation that was cut off."
        })
        
        return continuation_messages


    def _clean_continuation_text(self, original_text, continuation_text):
        """
        Clean continuation text to remove repetition from the original response.
        
        Args:
            original_text (str): The original response text
            continuation_text (str): The continuation text
            
        Returns:
            str: Cleaned continuation text
        """
        if not continuation_text.strip():
            return continuation_text
            
        # Get the last 200 characters of original text for overlap detection
        original_end = original_text[-200:].strip() if len(original_text) > 200 else original_text.strip()
        continuation_start = continuation_text[:200].strip()
        
        # Look for overlap and remove it
        words_original = original_end.split()
        words_continuation = continuation_start.split()
        
        # Find the longest common suffix/prefix overlap
        max_overlap = min(len(words_original), len(words_continuation), 10)  # Limit overlap check
        
        for overlap_len in range(max_overlap, 0, -1):
            if words_original[-overlap_len:] == words_continuation[:overlap_len]:
                # Remove the overlapping part from continuation
                remaining_words = words_continuation[overlap_len:]
                cleaned_continuation = ' '.join(remaining_words)
                logger.info(f"Removed {overlap_len} overlapping words from continuation")
                return cleaned_continuation
        
        # No significant overlap found, return original continuation
        return continuation_text

class GeminiClient(BaseAIClient):
    def __init__(self, api_key, model_name, model_instance=None):
        super().__init__(api_key, model_name, model_instance)
        genai.configure(api_key=self.api_key)
        self.client = genai.GenerativeModel(self.model_name)
        self.provider = 'gemini'

    def _get_default_max_tokens(self):
        """Get default max_tokens for Gemini models."""
        model_lower = self.model_name.lower()
        if 'gemini-pro' in model_lower:
            return 8192  # Gemini Pro capacity
        elif 'gemini-ultra' in model_lower:
            return 8192  # Gemini Ultra capacity
        else:
            return 8192  # Default for Gemini models

    def _stream_response(self, messages, temperature=None, max_tokens=None):
        """Gemini streaming implementation."""
        # Gemini's API has a different structure for messages
        gemini_messages = [msg['content'] for msg in messages if msg['role'] != 'system']
        
        # Set up generation config
        generation_config = {}
        if max_tokens is not None:
            generation_config["max_output_tokens"] = max_tokens
        elif self.model_instance and self.model_instance.max_tokens:
            generation_config["max_output_tokens"] = self.model_instance.max_tokens
        else:
            generation_config["max_output_tokens"] = self._get_default_max_tokens()
            
        if temperature is not None:
            generation_config["temperature"] = temperature

        try:
            # Use Gemini's streaming method
            response_stream = self.client.generate_content(
                gemini_messages, 
                generation_config=generation_config,
                stream=True
            )
            
            for chunk in response_stream:
                if hasattr(chunk, 'text') and chunk.text:
                    yield chunk.text
        except Exception as e:
            logger.error(f"Gemini streaming error: {e}")
            raise

    def _get_response_without_streaming(self, messages, temperature=None, max_tokens=None):
        """Gemini non-streaming fallback implementation."""
        # Gemini's API has a different structure for messages
        gemini_messages = [msg['content'] for msg in messages if msg['role'] != 'system']
        
        # Use max_tokens parameter if provided, else fall back to model_instance or default
        generation_config = {}
        if max_tokens is not None:
            generation_config["max_output_tokens"] = max_tokens
        elif self.model_instance and self.model_instance.max_tokens:
            generation_config["max_output_tokens"] = self.model_instance.max_tokens
            
        if temperature is not None:
            generation_config["temperature"] = temperature

        try:
            response = self.client.generate_content(gemini_messages, generation_config=generation_config)
            return {
                'status': 'success',
                'response': response.text,
                'raw_response': response,
                'completion_attempts': 1,
                'was_continued': False,
                'used_streaming': False
            }
        except Exception as e:
            logger.error(f"Gemini non-streaming error: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'response': '',
                'completion_attempts': 1,
                'was_continued': False,
                'used_streaming': False
            }

def get_ai_client(provider, api_key, model_name, model_instance=None):
    """
    Get an AI client for the specified provider.
    
    Args:
        provider (str): The AI provider ('openai', 'anthropic', 'gemini')
        api_key (str): API key for the provider
        model_name (str): Name of the model to use
        model_instance (LLMModel, optional): Database model instance containing configuration
    
    Returns:
        BaseAIClient: Configured AI client instance
    """
    provider = provider.lower()
    if provider == 'openai':
        return OpenAIClient(api_key, model_name, model_instance)
    elif provider == 'anthropic':
        return AnthropicClient(api_key, model_name, model_instance)
    elif provider == 'gemini':
        return GeminiClient(api_key, model_name, model_instance)
    else:
        raise ValueError(f"Unsupported AI provider: {provider}")
