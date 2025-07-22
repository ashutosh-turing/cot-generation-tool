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
from concurrent.futures import ThreadPoolExecutor

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

        # Extract Implementation section with multi-language support
        def extract_implementation(content):
            import re
            
            print(f"DEBUG: Starting code extraction from content of length {len(content)}")
            
            # Multiple strategies to find implementation code
            implementation_code = ""
            detected_language = "unknown"
            
            # Strategy 1: Look for "Implementation" section headers
            impl_patterns = [
                r"(#+\s*Implementation[\s\S]+?)(?=^#+\s|\Z)",
                r"(#+\s*Code[\s\S]+?)(?=^#+\s|\Z)",
                r"(#+\s*Solution[\s\S]+?)(?=^#+\s|\Z)",
                r"(#+\s*Answer[\s\S]+?)(?=^#+\s|\Z)",
                r"(#+\s*Final[\s\S]*?Code[\s\S]+?)(?=^#+\s|\Z)"
            ]
            
            for i, pattern in enumerate(impl_patterns):
                match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
                if match:
                    print(f"DEBUG: Found implementation section using pattern {i+1}")
                    section = match.group(1)
                    # Extract code blocks with multi-language support
                    code_blocks = re.findall(r"```(?:python|py|cpp|c\+\+|c|java|javascript|js|code)?\s*\n?([\s\S]+?)```", section)
                    if code_blocks:
                        implementation_code = "\n\n".join(code_blocks)
                        print(f"DEBUG: Extracted {len(code_blocks)} code blocks from section")
                        break
            
            # Strategy 2: If no section found, extract all code blocks from the entire content
            if not implementation_code:
                print("DEBUG: No section-based code found, trying all code blocks")
                all_code_blocks = re.findall(r"```(?:python|py|cpp|c\+\+|c|java|javascript|js|code)?\s*\n?([\s\S]+?)```", content)
                if all_code_blocks:
                    print(f"DEBUG: Found {len(all_code_blocks)} total code blocks")
                    # Filter out very short code blocks (likely examples)
                    substantial_blocks = [block for block in all_code_blocks if len(block.strip()) > 30]
                    if substantial_blocks:
                        implementation_code = "\n\n".join(substantial_blocks)
                        print(f"DEBUG: Using {len(substantial_blocks)} substantial code blocks")
                    else:
                        implementation_code = "\n\n".join(all_code_blocks)
                        print(f"DEBUG: Using all {len(all_code_blocks)} code blocks")
            
            # Strategy 3: Detect language and look for language-specific patterns
            if not implementation_code:
                print("DEBUG: No code blocks found, trying to detect language and extract patterns")
                
                # Detect programming language from content
                content_lower = content.lower()
                if any(keyword in content_lower for keyword in ['#include', 'iostream', 'std::', 'int main', 'cout', 'cin']):
                    detected_language = "cpp"
                elif any(keyword in content_lower for keyword in ['def ', 'import ', 'from ', 'print(', 'len(', 'range(']):
                    detected_language = "python"
                elif any(keyword in content_lower for keyword in ['public class', 'public static void', 'system.out', 'string[]']):
                    detected_language = "java"
                elif any(keyword in content_lower for keyword in ['function', 'console.log', 'var ', 'let ', 'const ']):
                    detected_language = "javascript"
                
                print(f"DEBUG: Detected language: {detected_language}")
                
                code_lines = []
                lines = content.split('\n')
                in_code_block = False
                current_block = []
                
                for line in lines:
                    # Skip markdown headers but preserve code comments
                    if line.strip().startswith('#') and not line.strip().startswith('# ') and not re.match(r'^\s*#.*', line):
                        if current_block:
                            code_lines.extend(current_block)
                            current_block = []
                        continue
                    
                    # Check if line looks like code based on detected language
                    is_code_line = False
                    
                    if detected_language == "cpp":
                        is_code_line = (line.strip() and 
                            (line.startswith('    ') or line.startswith('\t') or  # Indented code
                             any(line.strip().startswith(keyword) for keyword in 
                                 ['#include', 'using', 'int ', 'float ', 'double ', 'char ', 'bool ', 'void ', 'string ', 'if ', 'for ', 'while ', 'do ', 'switch ', 'case ', 'return ', 'cout', 'cin', 'std::', 'class ', 'struct ', 'namespace ']) or
                             line.strip().endswith(';') or line.strip().endswith('{') or line.strip().endswith('}') or
                             ('=' in line and not line.strip().startswith('=')) or
                             re.match(r'^\s*[a-zA-Z_]\w*\s*\(.*\)\s*[{;]?\s*$', line.strip()) or  # Function declarations/calls
                             '<<' in line or '>>' in line or  # Stream operators
                             line.strip() in ['{', '}']))  # Braces
                    
                    elif detected_language == "python":
                        is_code_line = (line.strip() and 
                            (line.startswith('    ') or line.startswith('\t') or  # Indented code
                             any(line.strip().startswith(keyword) for keyword in 
                                 ['def ', 'class ', 'import ', 'from ', 'if ', 'for ', 'while ', 'try:', 'except:', 'with ', 'return ', 'print(', 'len(']) or
                             ('=' in line and not line.strip().startswith('=') and not line.strip().startswith('==')) or
                             line.strip().endswith(':') or
                             re.match(r'^\s*[a-zA-Z_]\w*\s*\(.*\)\s*$', line.strip()) or
                             re.match(r'^\s*[a-zA-Z_]\w*\s*\[.*\]\s*$', line.strip()) or
                             line.strip().startswith('>>> ') or line.strip().startswith('... ')))
                    
                    elif detected_language == "java":
                        is_code_line = (line.strip() and 
                            (line.startswith('    ') or line.startswith('\t') or
                             any(line.strip().startswith(keyword) for keyword in 
                                 ['public ', 'private ', 'protected ', 'static ', 'class ', 'interface ', 'if ', 'for ', 'while ', 'do ', 'switch ', 'case ', 'return ', 'System.', 'import ', 'package ']) or
                             line.strip().endswith(';') or line.strip().endswith('{') or line.strip().endswith('}') or
                             ('=' in line and not line.strip().startswith('=')) or
                             line.strip() in ['{', '}']))
                    
                    else:  # Generic code detection
                        is_code_line = (line.strip() and 
                            (line.startswith('    ') or line.startswith('\t') or
                             '{' in line or '}' in line or
                             '(' in line and ')' in line or
                             '[' in line and ']' in line or
                             ('=' in line and not line.strip().startswith('=')) or
                             line.strip().endswith(';') or line.strip().endswith('{') or line.strip().endswith('}')))
                    
                    if is_code_line:
                        current_block.append(line)
                        in_code_block = True
                    elif in_code_block and line.strip() == '':
                        current_block.append(line)  # Keep empty lines in code blocks
                    elif in_code_block and line.strip():
                        # End of code block
                        if current_block:
                            code_lines.extend(current_block)
                            current_block = []
                        in_code_block = False
                
                # Add any remaining code block
                if current_block:
                    code_lines.extend(current_block)
                
                if code_lines:
                    implementation_code = '\n'.join(code_lines)
                    print(f"DEBUG: Extracted {len(code_lines)} lines of {detected_language}-like code")
            
            # Strategy 4: If still no code, look for any substantial text that might be code
            if not implementation_code:
                print("DEBUG: No language-specific patterns found, looking for any substantial code-like content")
                # Look for lines with common programming constructs
                potential_code_lines = []
                for line in content.split('\n'):
                    if (line.strip() and 
                        ('{' in line or '}' in line or 
                         '(' in line and ')' in line or
                         '[' in line and ']' in line or
                         '=' in line or ';' in line or
                         line.count(' ') > 3 or  # Indented or structured text
                         line.startswith('    ') or line.startswith('\t'))):  # Indented lines
                        potential_code_lines.append(line)
                
                if len(potential_code_lines) > 5:  # At least 5 lines that look code-like
                    implementation_code = '\n'.join(potential_code_lines)
                    print(f"DEBUG: Using {len(potential_code_lines)} potential code lines")
            
            result = implementation_code.strip()
            print(f"DEBUG: Final extracted code length: {len(result)}")
            print(f"DEBUG: Detected language: {detected_language}")
            if result:
                print(f"DEBUG: First 200 chars of extracted code: {result[:200]}...")
            
            return result

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
            
            print(f"DEBUG: Plagiarism result to parse: {plagiarism_result[:300]}...")
            
            score_patterns = [
                r"PLAGIARISM SCORE:\s*(\d{1,3})\s*%",
                r"Score:\s*(\d{1,3})\s*%",
                r"Plagiarism\s*Score:\s*(\d{1,3})\s*%",
                r"(\d{1,3})\s*%\s*plagiarism",
                r"plagiarism.*?(\d{1,3})\s*%",
                r"score.*?(\d{1,3})\s*%",
                r"(\d{1,3})\s*%\s*likelihood",
                r"likelihood.*?(\d{1,3})\s*%",
                r"(\d{1,3})\s*percent",
                r"(\d{1,3})\s*%"
            ]
            
            plagiarism_score = None
            for i, pattern in enumerate(score_patterns):
                score_match = re.search(pattern, plagiarism_result, re.IGNORECASE)
                if score_match:
                    try:
                        score = int(score_match.group(1))
                        if 0 <= score <= 100:  # Validate score range
                            plagiarism_score = score
                            print(f"DEBUG: Found plagiarism score {score}% using pattern {i+1}")
                            break
                    except (ValueError, IndexError):
                        continue
            
            # If no score found, try to infer from text
            if plagiarism_score is None:
                print("DEBUG: No numeric score found, trying to infer from text")
                lower_result = plagiarism_result.lower()
                
                # More comprehensive text analysis
                if any(phrase in lower_result for phrase in [
                    'no plagiarism', 'not plagiarized', 'original code', 'unique implementation',
                    'highly original', 'completely original', 'no copied', 'not copied'
                ]):
                    plagiarism_score = 10
                    print("DEBUG: Inferred very low plagiarism (10%)")
                elif any(phrase in lower_result for phrase in [
                    'low plagiarism', 'minimal plagiarism', 'slight similarity', 'mostly original',
                    'low likelihood', 'unlikely to be copied', 'minor similarities'
                ]):
                    plagiarism_score = 25
                    print("DEBUG: Inferred low plagiarism (25%)")
                elif any(phrase in lower_result for phrase in [
                    'moderate plagiarism', 'some similarities', 'partial copying', 'mixed originality',
                    'moderate likelihood', 'some copied elements', 'moderate concern'
                ]):
                    plagiarism_score = 50
                    print("DEBUG: Inferred moderate plagiarism (50%)")
                elif any(phrase in lower_result for phrase in [
                    'high plagiarism', 'likely copied', 'probable plagiarism', 'significant similarities',
                    'high likelihood', 'mostly copied', 'substantial copying'
                ]):
                    plagiarism_score = 75
                    print("DEBUG: Inferred high plagiarism (75%)")
                elif any(phrase in lower_result for phrase in [
                    'definitely copied', 'clearly plagiarized', 'stolen code', 'direct copy',
                    'very high plagiarism', 'almost certainly copied', 'obvious plagiarism'
                ]):
                    plagiarism_score = 90
                    print("DEBUG: Inferred very high plagiarism (90%)")
                else:
                    # Try to find any percentage mentioned in the text
                    percentage_matches = re.findall(r'(\d{1,3})\s*(?:%|percent)', lower_result)
                    if percentage_matches:
                        try:
                            score = int(percentage_matches[0])
                            if 0 <= score <= 100:
                                plagiarism_score = score
                                print(f"DEBUG: Found percentage {score}% in text")
                        except ValueError:
                            pass
                    
                    if plagiarism_score is None:
                        plagiarism_score = 0  # Default to 0 if cannot determine
                        print("DEBUG: Could not determine plagiarism score, defaulting to 0%")
            
            print(f"DEBUG: Final plagiarism score: {plagiarism_score}%")
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

        # Enable concurrent processing with a thread pool
        max_workers = 16  # Adjust based on server resources
        executor = ThreadPoolExecutor(max_workers=max_workers)
        streaming_pull_future = subscriber.subscribe(
            subscription_path, callback=callback
        )
        self.stdout.write(f"Listening for messages on {subscription_path} (no custom executor, using default threading)...")

        try:
            streaming_pull_future.result()
        except KeyboardInterrupt:
            streaming_pull_future.cancel()
            self.stdout.write("Subscription cancelled.")
