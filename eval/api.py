
def check_file_type(file_name):
    if file_name.endswith(".json"):
        return "JSON"
    elif file_name.endswith(".py"):
        return "PYTHON"
    else:
        return "UNKNOWN"
    
# Function to check the logical consistency of chain of thought in the json
def check_logical_consistency(json_data):
    # Check if the chain of thought is consistent
    # Return True if consistent, False otherwise
    pass

def apply_function(file_name):
    file_type = check_file_type(file_name)
    if file_type == "JSON":
        pass
    elif file_type == "PYTHON":
        # Apply the function for Python files
        pass
    else:
        # Handle other file types or raise an error
        pass

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
import json
import logging
from openai import OpenAI
from django.conf import settings
import time

logger = logging.getLogger(__name__)

@csrf_exempt
@require_http_methods(["GET"])
def get_llm_models(request):
    """
    API endpoint to get available LLM models from the database
    """
    try:
        # Log the request for debugging
        logger.info("Get LLM models request received")
        
        from eval.models import LLMModel
        models = LLMModel.objects.filter(is_active=True).order_by('name')
        
        model_data = [
            {
                "id": str(model.id),  # Convert to string to ensure JSON serialization
                "name": model.name,
                "provider": model.get_provider_display() if hasattr(model, 'get_provider_display') else (model.provider if hasattr(model, 'provider') else "Unknown"),
                "description": model.description if hasattr(model, 'description') else ""
            }
            for model in models
        ]
        
        # If no models found in DB, provide some defaults
        if not model_data:
            logger.warning("No models found in database, using defaults")
            model_data = [
                {"id": "gpt-4", "name": "GPT-4", "provider": "OpenAI"},
                {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "provider": "OpenAI"},
                {"id": "claude-3-opus", "name": "Claude 3 Opus", "provider": "Anthropic"},
                {"id": "claude-3-sonnet", "name": "Claude 3 Sonnet", "provider": "Anthropic"}
            ]
        
        logger.info(f"Returning {len(model_data)} models")
        return JsonResponse({"models": model_data})
    except Exception as e:
        logger.error(f"Error fetching models: {str(e)}")
        
        # Return default models if there's an error
        default_models = [
            {"id": "gpt-4", "name": "GPT-4", "provider": "OpenAI"},
            {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "provider": "OpenAI"}
        ]
        return JsonResponse({"models": default_models})

@csrf_exempt
@require_http_methods(["POST"])
def generate_response(request):
    """
    API endpoint to generate responses from an LLM model
    """
    try:
        # Log the request for debugging
        logger.info(f"Generate response request received: {request.body[:100]}...")
        
        data = json.loads(request.body)
        model_id = data.get('model_id')
        prompt = data.get('prompt')
        num_replies = min(int(data.get('num_replies', 1)), 5)  # Limit to 5 max replies
        
        if not model_id or not prompt:
            return JsonResponse({"error": "Missing required parameters"}, status=400)
        
        logger.info(f"Generating {num_replies} responses with model {model_id}")
        
        # Skip authentication check for this endpoint to allow anonymous access
        # This is important for the ground truth validation feature
        
        # Get the model from the database
        try:
            from eval.models import LLMModel
            model = LLMModel.objects.get(id=model_id)
            logger.info(f"Found model in database: {model.name}")
            # Call the appropriate LLM API based on the model
            responses = call_llm_api(model, prompt, num_replies)
        except LLMModel.DoesNotExist:
            logger.warning(f"Model with ID {model_id} not found in database, using ID as model name")
            # If model not found in database, use the ID as the model name
            responses = call_llm_api(model_id, prompt, num_replies)
        
        return JsonResponse({"replies": responses})
        
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error generating response: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def validate_with_llm(request):
    """
    API endpoint to validate model replies against ground truth using LLM
    """
    try:
        # Log the request for debugging
        logger.info(f"Validate with LLM request received: {request.body[:100]}...")
        
        data = json.loads(request.body)
        validation_model_id = data.get('validation_model_id', 'claude-3-opus-20240229')  # Default to o3-mini
        ground_truth = data.get('ground_truth')
        model_reply = data.get('model_reply')
        
        if not ground_truth or not model_reply:
            return JsonResponse({"error": "Missing required parameters: ground_truth or model_reply"}, status=400)
        
        logger.info(f"Validating reply using model {validation_model_id}")
        
        # Get the validation model from the database
        try:
            from eval.models import LLMModel
            validation_model = LLMModel.objects.get(id=validation_model_id)
            logger.info(f"Found validation model in database: {validation_model.name}")
            # Call the validation function
            validation_result = perform_llm_validation(validation_model, ground_truth, model_reply)
        except LLMModel.DoesNotExist:
            logger.warning(f"Validation model with ID {validation_model_id} not found in database, using ID as model name")
            # If model not found in database, use the ID as the model name
            validation_result = perform_llm_validation(validation_model_id, ground_truth, model_reply)
        
        return JsonResponse(validation_result)
        
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error validating with LLM: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)

def perform_llm_validation(model, ground_truth, model_reply):
    """
    Use an LLM to validate how well a model reply matches the ground truth
    Returns a structured validation result
    """
    try:
        # Determine if model is a LLMModel instance or a string
        if hasattr(model, 'name'):
            model_name = model.name
            model_id = str(model.id)
        else:
            model_name = str(model)
            model_id = str(model)
        
        logger.info(f"Using validation model: {model_name}")
        
        # Create the validation prompt
        validation_prompt = f"""
You are an expert evaluator tasked with determining how well a model's reply matches the ground truth answer.

Ground Truth: {ground_truth}

Model Reply: {model_reply}

Evaluate how well the model reply matches the ground truth in terms of:
1. Semantic meaning
2. Factual correctness
3. Completeness of information

Provide your evaluation in the following JSON format:
{{
  "match_category": "one of [Exact, Strong, Moderate, Weak, Different]",
  "similarity_score": "a number between 0 and 100",
  "reasoning": "brief explanation of your evaluation"
}}

Where match categories mean:
- Exact: The reply is identical or nearly identical to the ground truth
- Strong: The reply conveys the same meaning with different wording
- Moderate: The reply captures the main points but misses some details or adds irrelevant information
- Weak: The reply has some relevant information but misses key points or contains inaccuracies
- Different: The reply is substantially different from the ground truth

Your response should be ONLY the JSON object, nothing else.
"""
        
        start_time = time.time()
        
        # Call the appropriate LLM API based on the model
        if "gpt" in model_name.lower():
            # Use API key from model if available, else error
            api_key = getattr(model, "api_key", None)
            if not api_key:
                return {
                    "error": "OpenAI API key not found in model object.",
                    "match_category": "Unknown",
                    "similarity_score": 0,
                    "reasoning": "Could not validate due to missing OpenAI API key"
                }
            client = OpenAI(
                api_key=api_key,
                base_url=getattr(settings, "OPENAI_API_URL", "https://api.openai.com/v1")
            )
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are an expert evaluator."},
                    {"role": "user", "content": validation_prompt}
                ],
                temperature=0.1,  # Low temperature for consistent evaluations
            )
            validation_text = response.choices[0].message.content.strip()
            
        # Anthropic models
        elif "claude" in model_name.lower():
            try:
                import anthropic
                # Use API key from model if available, else error
                api_key = getattr(model, "api_key", None)
                if not api_key:
                    return {
                        "error": "Anthropic API key not found in model object.",
                        "match_category": "Unknown",
                        "similarity_score": 0,
                        "reasoning": "Could not validate due to missing Anthropic API key"
                    }
                claude_client = anthropic.Anthropic(api_key=api_key)
                
                response = claude_client.messages.create(
                    model=model_name,
                    max_tokens=1000,
                    messages=[
                        {"role": "user", "content": validation_prompt}
                    ],
                    temperature=0.1,
                )
                validation_text = response.content[0].text
            except ImportError:
                # Fallback if Anthropic SDK is not available
                return {
                    "error": "Anthropic SDK not available",
                    "match_category": "Unknown",
                    "similarity_score": 0,
                    "reasoning": "Could not validate due to missing Anthropic SDK"
                }
            except Exception as e:
                logger.error(f"Anthropic API error: {str(e)}")
                return {
                    "error": f"Anthropic API error: {str(e)}",
                    "match_category": "Unknown",
                    "similarity_score": 0,
                    "reasoning": f"Could not validate due to Anthropic API error: {str(e)}"
                }
        
        # Google models
        elif "gemini" in model_name.lower():
            try:
                import google.generativeai as genai
                api_key = getattr(model, "api_key", None)
                genai.configure(api_key=api_key)
                
                genai_model = genai.GenerativeModel(model_name)
                response = genai_model.generate_content(validation_prompt)
                validation_text = response.text
            except ImportError:
                # Fallback if Google SDK is not available
                return {
                    "error": "Google Generative AI SDK not available",
                    "match_category": "Unknown",
                    "similarity_score": 0,
                    "reasoning": "Could not validate due to missing Google SDK"
                }
        
        # Other models - use the same pattern as in call_llm_api
        else:
            # Use the existing call_llm_api function with a single reply
            validation_text = call_llm_api(model, validation_prompt, 1)[0]
        
        elapsed_time = round(time.time() - start_time, 2)
        
        # Parse the JSON response
        try:
            # Extract JSON if it's embedded in text
            if '{' in validation_text and '}' in validation_text:
                json_start = validation_text.find('{')
                json_end = validation_text.rfind('}') + 1
                json_str = validation_text[json_start:json_end]
                validation_result = json.loads(json_str)
            else:
                validation_result = json.loads(validation_text)
            
            # Ensure all required fields are present
            if 'match_category' not in validation_result:
                validation_result['match_category'] = 'Unknown'
            if 'similarity_score' not in validation_result:
                validation_result['similarity_score'] = 0
            if 'reasoning' not in validation_result:
                validation_result['reasoning'] = 'No reasoning provided'
            
            # Add metadata
            validation_result['validation_model'] = model_name
            validation_result['validation_time'] = elapsed_time
            
            return validation_result
            
        except json.JSONDecodeError:
            # If JSON parsing fails, return a structured error with the raw text
            logger.error(f"Failed to parse validation result as JSON: {validation_text}")
            return {
                "error": "Failed to parse validation result",
                "match_category": "Error",
                "similarity_score": 0,
                "reasoning": "The validation model did not return valid JSON",
                "raw_response": validation_text,
                "validation_model": model_name,
                "validation_time": elapsed_time
            }
    
    except Exception as e:
        logger.error(f"Error in perform_llm_validation: {str(e)}")
        return {
            "error": str(e),
            "match_category": "Error",
            "similarity_score": 0,
            "reasoning": f"Validation failed with error: {str(e)}",
            "validation_model": getattr(model, 'name', str(model)),
            "validation_time": 0
        }

@csrf_exempt
@require_http_methods(["POST"])
def review_colab(request):
    """
    API endpoint to queue a review of Google Colab content.
    This view now publishes a job to Pub/Sub instead of processing it directly.
    """
    try:
        data = json.loads(request.body)
        colab_content = data.get("colab_content", "")
        models = data.get("models", [])
        question_id = data.get("question_id", "")

        if not colab_content or not models:
            return JsonResponse({"success": False, "error": "Missing colab_content or models."}, status=400)

        from .utils.pubsub import publish_message
        import uuid
        
        job_id = str(uuid.uuid4())
        
        # For each model, publish a separate job to the queue
        for model_id in models:
            data_to_publish = {
                "type": "review_colab",
                "job_id": job_id,
                "question_id": str(question_id),
                "user_id": request.user.id,
                "colab_content": colab_content,
                "model_id": model_id,
            }
            publish_message(data_to_publish)

        return JsonResponse({
            "success": True,
            "job_id": job_id,
            "message": f"Your review requests for {len(models)} models have been queued."
        })

    except Exception as e:
        logger.error(f"Error in review_colab: {str(e)}")
        return JsonResponse({"success": False, "error": str(e)}, status=500)

@require_http_methods(["GET"])
def get_review_results(request, job_id):
    """
    API endpoint to poll for review results for a given job_id.
    Expects a GET request with a 'model_ids' query parameter (comma-separated).
    """
    if request.method != "GET":
        return JsonResponse({"success": False, "error": "Invalid request method."})

    model_ids_str = request.GET.get('model_ids', '')
    if not model_ids_str:
        return JsonResponse({"success": False, "error": "Missing 'model_ids' parameter."})

    model_ids = model_ids_str.split(',')
    results = {}
    completed_models = []

    from django.core.cache import cache
    from eval.models import LLMModel

    for model_id in model_ids:
        cache_key = f"analysis_result_{job_id}_{model_id}"
        result = cache.get(cache_key)
        if result:
            model = LLMModel.objects.get(id=model_id)
            results[model_id] = {
                "model_name": model.name,
                "result": result
            }
            completed_models.append(model_id)

    return JsonResponse({
        "success": True,
        "job_id": job_id,
        "results": results,
        "completed_models": completed_models,
        "is_complete": len(completed_models) == len(model_ids)
    })

def call_llm_api(model, prompt, num_replies):
    """
    Call the appropriate LLM API based on the model
    Similar to evaluate_with_llm in processor/utils.py
    """
    from django.conf import settings  # Ensure settings is always available
    responses = []
    
    try:
        # Determine if model is a LLMModel instance or a string
        if hasattr(model, 'name'):
            model_name = model.name
            model_id = str(model.id)
            model_provider = model.provider if hasattr(model, 'provider') else "Unknown"
        else:
            model_name = str(model)
            model_id = str(model)
            model_provider = "Unknown"
        
        logger.info(f"Processing model: {model_name} (ID: {model_id}, Provider: {model_provider})")
        
        # OpenAI models
        if "gpt" in model_name.lower():
            # Use API key from model if available, else error
            api_key = getattr(model, "api_key", None)
            if not api_key:
                raise Exception("OpenAI API key not found in model object.")
            client = OpenAI(
                api_key=api_key,
                base_url=getattr(settings, "OPENAI_API_URL", "https://api.openai.com/v1")
            )
            
            for _ in range(num_replies):
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                )
                responses.append(response.choices[0].message.content.strip())
        
        # Anthropic models
        elif "claude" in model_name.lower():
            # If using Anthropic's API
            try:
                import anthropic
                # Use API key from model if available, else error
                api_key = getattr(model, "api_key", None)
                if not api_key:
                    raise Exception("Anthropic API key not found in model object.")
                claude_client = anthropic.Anthropic(api_key=api_key)
                
                for _ in range(num_replies):
                    response = claude_client.messages.create(
                        model=model_name,
                        max_tokens=1000,
                        messages=[
                            {"role": "user", "content": prompt}
                        ]
                    )
                    responses.append(response.content[0].text)
            except ImportError:
                # Fallback to mock responses if Anthropic SDK is not available
                responses = [f"Claude would respond to: {prompt} (response #{i+1})" for i in range(num_replies)]
            except Exception as e:
                logger.error(f"Anthropic API error: {str(e)}")
                responses = [f"Error with Anthropic API: {str(e)}"]
        
        # Google models
        elif "gemini" in model_name.lower():
            # If using Google's API
            try:
                import google.generativeai as genai
                # Use API key from model if available, else error
                api_key = getattr(model, "api_key", None)
                genai.configure(api_key=api_key)
                
                genai_model = genai.GenerativeModel(model_name)
                for _ in range(num_replies):
                    response = genai_model.generate_content(prompt)
                    responses.append(response.text)
            except ImportError:
                # Fallback to mock responses if Google SDK is not available
                responses = [f"Gemini would respond to: {prompt} (response #{i+1})" for i in range(num_replies)]
        
        # DeepSeek models (similar to processor/utils.py)
        elif "deepseek" in model_name.lower():
            try:
                # Get DeepSeek API key and remove any quotes
                # Use API key from model if available, else error
                deepseek_key = getattr(model, "api_key", None)
                logger.info(f"Using DeepSeek API with base URL: {deepseek_key}")
                
                # Create DeepSeek client
                deepseek_client = OpenAI(
                    api_key=deepseek_key,
                    base_url=settings.DEEPSEEK_API_URL
                )
                
                for _ in range(num_replies):
                    response = deepseek_client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": "You are a helpful assistant."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.7,
                    )
                    responses.append(response.choices[0].message.content.strip())
                    logger.info(f"DeepSeek response received, length: {len(responses[-1])}")
            except Exception as e:
                logger.error(f"DeepSeek API error: {str(e)}")
                responses.append(f"Error with DeepSeek API: {str(e)}")
        
        # LLaMA models with Fireworks (similar to processor/utils.py)
        elif "llama" in model_name.lower():
            try:
                from fireworks.client import Fireworks
                
                # Get Fireworks API key
                fireworks_api_key = getattr(model, "api_key", None)
                logger.info(f"Using Fireworks API for LLaMA model with base URL: {getattr(settings, 'FIREWORKS_API_URL', None)}")
                
                # Create Fireworks client
                # If Fireworks supports base_url, use it; otherwise, fallback to default
                try:
                    fireworks_client = Fireworks(api_key=fireworks_api_key, base_url=settings.FIREWORKS_API_URL)
                except TypeError:
                    # If base_url is not supported, fallback to default constructor
                    fireworks_client = Fireworks(api_key=fireworks_api_key)
                
                # Use the standard model name format for Fireworks
                # If the model name already contains the full path, use it as is
                if "accounts/fireworks/models/" in model_name:
                    fireworks_model_name = model_name
                else:
                    # Otherwise, use a fixed model name that's known to work
                    fireworks_model_name = "accounts/fireworks/models/llama-v3-70b-instruct"
                    # Alternatively, append the model name to the path
                    # fireworks_model_name = "accounts/fireworks/models/" + model_name
                
                logger.info(f"Using Fireworks model: {fireworks_model_name}")
                
                for _ in range(num_replies):
                    response = fireworks_client.chat.completions.create(
                        model=fireworks_model_name,
                        messages=[
                            {"role": "system", "content": "You are a helpful assistant."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.7,
                    )
                    responses.append(response.choices[0].message.content.strip())
                    logger.info(f"Fireworks response received, length: {len(responses[-1])}")
            except Exception as e:
                logger.error(f"Fireworks API error: {str(e)}")
                responses.append(f"Error with Fireworks API: {str(e)}")
        
        # Default fallback for unknown models - use the evaluate_with_llm function from processor/utils.py
        else:
            try:
                from processor.utils import evaluate_with_llm
                from processor.models import Prompt

                # Try to get an API key from the model if available
                api_key = getattr(model, "api_key", None)
                if not api_key:
                    raise Exception("API key not found in model object for fallback evaluation.")

                # Create a dummy prompt object
                dummy_prompt = Prompt(system_message="You are a helpful assistant.")

                # Create a JSON-like structure with the prompt
                json_result = {
                    "messages": [
                        {},
                        {"reasoning": {"process": [{"summary": prompt}]}}
                    ]
                }

                # Call the existing evaluation function
                for _ in range(num_replies):
                    response = evaluate_with_llm(json_result, api_key, model, dummy_prompt)
                    responses.append(response)

                logger.info(f"Used evaluate_with_llm for model {model_name}")
            except Exception as eval_error:
                logger.error(f"Error using evaluate_with_llm: {str(eval_error)}")
                # Fallback to mock responses
                responses = [f"Model {model_name} would respond to: {prompt} (response #{i+1})" for i in range(num_replies)]

    except Exception as e:
        logger.error(f"Error calling LLM API: {str(e)}")
        # Ensure responses is always defined as a list
        responses = [f"Error generating response: {str(e)}"]
    
    return responses
