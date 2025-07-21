import os
import json
import time
from django.core.management.base import BaseCommand
from google.cloud import pubsub_v1
from django.conf import settings
from eval.utils.ai_client import get_ai_client
from eval.models import LLMModel, TrainerTask, LLMJob
from django.contrib.auth.models import User
from django.core.cache import cache
from eval.utils.pubsub import publish_notification
from django.utils import timezone

def process_trainer_question_analysis(data):
    """Processes a trainer question analysis job."""
    job_id = data.get("job_id")
    llm_job = None
    
    try:
        # Get the LLMJob record
        try:
            llm_job = LLMJob.objects.get(job_id=job_id)
            llm_job.mark_processing()
        except LLMJob.DoesNotExist:
            print(f"LLMJob with id {job_id} not found")
            return
        
        question_id = data.get("question_id")
        user_id = data.get("user_id")
        system_message = data.get("system_message")
        full_input = data.get("full_input")
        model_id = data.get("model_id")

        # Retry logic to handle potential race conditions
        model_obj = None
        for _ in range(5):  # Retry up to 5 times
            try:
                model_obj = LLMModel.objects.get(id=model_id)
                break  # Exit loop if model is found
            except LLMModel.DoesNotExist:
                print(f"LLMModel with id {model_id} not found, retrying in 2 seconds...")
                time.sleep(2)
        
        if not model_obj:
            error_msg = f"LLMModel with id {model_id} not found after multiple retries."
            if llm_job:
                llm_job.mark_failed(error_msg)
            raise Exception(error_msg)

        user = User.objects.get(id=user_id) if user_id else None

        # Use API key from model_obj only; all keys are managed in the database
        api_key = model_obj.api_key
        client = get_ai_client(model_obj.provider, api_key, model_obj.name)

        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": full_input})

        result = client.get_response(messages)

        # Store the result in both cache and database
        cache_key = f"analysis_result_{job_id}_{model_id}"
        if result.get('status') == 'success':
            result_data = {"success": True, "result": result['response']}
            # Store in cache for backward compatibility
            cache.set(cache_key, result_data, timeout=3600)
            # Store in database
            if llm_job:
                llm_job.mark_completed(result_data)
        else:
            error_message = result.get('error', 'Unknown error')
            result_data = {"success": False, "error": error_message}
            # Store in cache for backward compatibility
            cache.set(cache_key, result_data, timeout=3600)
            # Store in database
            if llm_job:
                llm_job.mark_failed(error_message)

        print(f"Processed trainer_question_analysis for question {question_id}. Result stored in cache with key {cache_key}")

        # Publish a notification
        publish_notification({
            "type": "trainer_question_analysis_complete",
            "job_id": job_id,
            "question_id": question_id,
            "user_id": user_id,
            "model_id": model_id,
            "result": result_data
        })

    except Exception as e:
        print(f"Error processing trainer_question_analysis: {e}")
        # Store error in both cache and database
        if job_id:
            model_id = data.get("model_id")
            if model_id:
                cache_key = f"analysis_result_{job_id}_{model_id}"
                cache.set(cache_key, {"success": False, "error": str(e)}, timeout=3600)
            if llm_job:
                llm_job.mark_failed(str(e))


def call_llm_api(model_obj, prompt, n):
    """A helper function to call the LLM API and get n responses."""
    # Use API key from model_obj only; all keys are managed in the database
    api_key = model_obj.api_key
    client = get_ai_client(model_obj.provider, api_key, model_obj.name)
    
    messages = [{"role": "user", "content": prompt}]
    
    responses = []
    for _ in range(n):
        result = client.get_response(messages)
        if result['status'] == 'success':
            responses.append(result['response'])
        else:
            responses.append(f"Error: {result.get('error', 'Unknown error')}")
            
    return responses


def process_review_colab(data):
    """Processes a review colab job."""
    job_id = data.get("job_id")
    llm_job = None
    
    try:
        # Get the LLMJob record
        try:
            llm_job = LLMJob.objects.get(job_id=job_id)
            llm_job.mark_processing()
        except LLMJob.DoesNotExist:
            print(f"LLMJob with id {job_id} not found")
            return
        
        question_id = data.get("question_id")
        user_id = data.get("user_id")
        colab_content = data.get("colab_content")
        model_id = data.get("model_id")

        model_obj = LLMModel.objects.get(id=model_id)
        user = User.objects.get(id=user_id) if user_id else None

        # Extract Implementation section with improved code extraction
        def extract_implementation(content):
            import re
            
            # Multiple strategies to find implementation code
            implementation_code = ""
            
            # Strategy 1: Look for "Implementation" section headers
            impl_patterns = [
                r"(#+\s*Implementation[\s\S]+?)(^#+\s|\Z)",
                r"(#+\s*Code[\s\S]+?)(^#+\s|\Z)",
                r"(#+\s*Solution[\s\S]+?)(^#+\s|\Z)",
                r"(#+\s*Answer[\s\S]+?)(^#+\s|\Z)"
            ]
            
            for pattern in impl_patterns:
                match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
                if match:
                    section = match.group(1)
                    # Extract code blocks (```...```)
                    code_blocks = re.findall(r"```(?:python|py|code)?\n?([\s\S]+?)```", section)
                    if code_blocks:
                        implementation_code = "\n\n".join(code_blocks)
                        break
            
            # Strategy 2: If no section found, extract all code blocks from the entire content
            if not implementation_code:
                all_code_blocks = re.findall(r"```(?:python|py|code)?\n?([\s\S]+?)```", content)
                if all_code_blocks:
                    # Filter out very short code blocks (likely examples)
                    substantial_blocks = [block for block in all_code_blocks if len(block.strip()) > 50]
                    if substantial_blocks:
                        implementation_code = "\n\n".join(substantial_blocks)
                    else:
                        implementation_code = "\n\n".join(all_code_blocks)
            
            # Strategy 3: Look for Python code patterns even without code blocks
            if not implementation_code:
                # Look for lines that start with common Python patterns
                python_patterns = [
                    r"^(def\s+\w+.*?)(?=^def\s|\Z)",
                    r"^(class\s+\w+.*?)(?=^class\s|^def\s|\Z)",
                    r"^(import\s+.*?)(?=^$|\Z)",
                    r"^(from\s+.*?)(?=^$|\Z)"
                ]
                
                code_lines = []
                lines = content.split('\n')
                in_code_block = False
                
                for line in lines:
                    # Skip markdown headers and text
                    if line.strip().startswith('#') and not line.strip().startswith('# '):
                        continue
                    
                    # Check if line looks like Python code
                    if (line.strip() and 
                        (line.startswith('    ') or  # Indented code
                         line.startswith('\t') or   # Tab indented
                         any(line.strip().startswith(keyword) for keyword in 
                             ['def ', 'class ', 'import ', 'from ', 'if ', 'for ', 'while ', 'try:', 'except:', 'with ']) or
                         '=' in line and not line.strip().startswith('=') or  # Assignment
                         line.strip().endswith(':') or  # Control structures
                         re.match(r'^\s*[a-zA-Z_]\w*\s*\(.*\)\s*$', line.strip()))):  # Function calls
                        code_lines.append(line)
                        in_code_block = True
                    elif in_code_block and line.strip() == '':
                        code_lines.append(line)  # Keep empty lines in code blocks
                    elif in_code_block and not line.strip().startswith('#'):
                        in_code_block = False
                
                if code_lines:
                    implementation_code = '\n'.join(code_lines)
            
            return implementation_code.strip()

        implementation_code = extract_implementation(colab_content)
        
        # Debug: Print extracted code length and first few lines
        if implementation_code.strip():
            print(f"DEBUG: Extracted {len(implementation_code)} characters of implementation code")
            print(f"DEBUG: First 200 chars: {implementation_code[:200]}...")
        else:
            print("DEBUG: No implementation code extracted")
            print(f"DEBUG: Content length: {len(colab_content)}")
            print(f"DEBUG: Content preview: {colab_content[:500]}...")

        # 1. Grammar check
        grammar_prompt = (
            "You are a grammar expert. Review the following notebook content for grammar and language issues. "
            "List all errors and suggest corrections. If there are no issues, say 'No grammar issues found.'\n\n"
            f"Notebook Content:\n{colab_content}"
        )
        grammar_result = call_llm_api(model_obj, grammar_prompt, 1)[0]

        # 2. Plagiarism check (on implementation code)
        if implementation_code.strip():
            plagiarism_prompt = (
                "You are an expert code plagiarism detector. Analyze the following code for potential plagiarism.\n\n"
                "Please evaluate:\n"
                "1. Code originality and uniqueness\n"
                "2. Common patterns vs. copied solutions\n"
                "3. Variable naming conventions\n"
                "4. Code structure and style\n"
                "5. Likelihood of being copied from online sources\n\n"
                "Provide a plagiarism score from 0-100% where:\n"
                "- 0-20%: Highly original code\n"
                "- 21-40%: Some common patterns but mostly original\n"
                "- 41-60%: Mix of common and potentially copied elements\n"
                "- 61-80%: Likely contains copied code segments\n"
                "- 81-100%: High likelihood of plagiarism\n\n"
                "Format your response as:\n"
                "PLAGIARISM SCORE: [X]%\n"
                "ANALYSIS: [Your detailed analysis]\n\n"
                f"Code to analyze:\n{implementation_code}"
            )
            plagiarism_result = call_llm_api(model_obj, plagiarism_prompt, 1)[0]
            
            # Try to extract a score from the response with improved regex
            import re
            score_patterns = [
                r"PLAGIARISM SCORE:\s*(\d{1,3})\s*%",
                r"Score:\s*(\d{1,3})\s*%",
                r"(\d{1,3})\s*%\s*plagiarism",
                r"plagiarism.*?(\d{1,3})\s*%",
                r"(\d{1,3})\s*%"
            ]
            
            plagiarism_score = None
            for pattern in score_patterns:
                score_match = re.search(pattern, plagiarism_result, re.IGNORECASE)
                if score_match:
                    try:
                        score = int(score_match.group(1))
                        if 0 <= score <= 100:  # Validate score range
                            plagiarism_score = score
                            break
                    except (ValueError, IndexError):
                        continue
            
            # If no score found, try to infer from text
            if plagiarism_score is None:
                lower_result = plagiarism_result.lower()
                if any(word in lower_result for word in ['no plagiarism', 'original', 'unique', 'not copied']):
                    plagiarism_score = 15
                elif any(word in lower_result for word in ['low', 'minimal', 'slight']):
                    plagiarism_score = 25
                elif any(word in lower_result for word in ['moderate', 'some', 'partial']):
                    plagiarism_score = 50
                elif any(word in lower_result for word in ['high', 'likely', 'probable']):
                    plagiarism_score = 75
                elif any(word in lower_result for word in ['copied', 'plagiarized', 'stolen']):
                    plagiarism_score = 90
                else:
                    plagiarism_score = 0  # Default to 0 if cannot determine
        else:
            plagiarism_result = "No implementation code found to analyze for plagiarism."
            plagiarism_score = 0

        # 3. Code quality and improvements
        code_quality_prompt = (
            "You are a code reviewer. Review the following code for quality, readability, and best practices. "
            "Suggest any improvements or refactoring. If the code is good, say 'Code quality is good.'\n\n"
            f"Code:\n{implementation_code or '[No code found]'}"
        )
        code_quality_result = call_llm_api(model_obj, code_quality_prompt, 1)[0]

        # Try to split improvements if present
        improvements = ""
        if "improvement" in code_quality_result.lower():
            improvements = code_quality_result
        else:
            improvements = ""

        # Construct the result dictionary
        result = {
            "grammar": grammar_result,
            "plagiarism_score": plagiarism_score,
            "plagiarism_result": plagiarism_result,
            "code_quality": code_quality_result,
            "improvements": improvements,
            "success": True
        }

        # Store the result in both cache and database
        if job_id:
            cache_key = f"analysis_result_{job_id}_{model_id}"
            cache.set(cache_key, result, timeout=3600)  # Cache for 1 hour
            
            # Store in database
            if llm_job:
                llm_job.mark_completed(result)
            
            print(f"Processed review_colab for question {question_id}. Result stored in cache with key {cache_key}")

            # Publish a notification
            publish_notification({
                "type": "review_colab_complete",
                "job_id": job_id,
                "question_id": question_id,
                "user_id": user_id,
                "model_id": model_id,
                "result": result
            })
        else:
            print(f"Processed review_colab for question {question_id}, but no job_id was provided. Result not cached.")

    except Exception as e:
        print(f"Error processing review_colab: {e}")
        # Store error in both cache and database
        if job_id:
            model_id = data.get("model_id")
            if model_id:
                cache_key = f"analysis_result_{job_id}_{model_id}"
                cache.set(cache_key, {"success": False, "error": str(e)}, timeout=3600)
            if llm_job:
                llm_job.mark_failed(str(e))


class Command(BaseCommand):
    help = 'Listens for and processes LLM jobs from a Pub/Sub subscription.'

    def handle(self, *args, **options):
        # Set the GOOGLE_APPLICATION_CREDENTIALS environment variable
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.SERVICE_ACCOUNT_FILE
        
        project_id = settings.GOOGLE_CLOUD_PROJECT_ID
        subscription_id = "llm-requests-subscription"

        subscriber = pubsub_v1.SubscriberClient()
        subscription_path = subscriber.subscription_path(project_id, subscription_id)

        def callback(message):
            print(f"Received message: {message.data}")
            try:
                data = json.loads(message.data)
                job_type = data.get("type")

                if job_type == "trainer_question_analysis":
                    process_trainer_question_analysis(data)
                elif job_type == "review_colab":
                    process_review_colab(data)
                else:
                    print(f"Unknown job type: {job_type}")

                message.ack()
            except Exception as e:
                print(f"Error processing message: {e}")
                message.nack()

        streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)
        self.stdout.write(f"Listening for messages on {subscription_path}...")

        try:
            streaming_pull_future.result()
        except KeyboardInterrupt:
            streaming_pull_future.cancel()
            self.stdout.write("Subscription cancelled.")
