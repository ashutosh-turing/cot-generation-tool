from django.core.management.base import BaseCommand
from eval.models import Validation

class Command(BaseCommand):
    help = 'Create sample validation criteria for demonstration'

    def handle(self, *args, **options):
        validations = [
            {
                'name': 'Grammar Check',
                'description': 'Validates proper English grammar in code comments and documentation',
                'validation': '''
def validate_grammar(data):
    """
    Check for basic grammar issues in the response text.
    Returns (success: bool, message: str)
    """
    try:
        response_text = ""
        if "messages" in data:
            for message in data["messages"]:
                if message.get("role") == "assistant":
                    for content in message.get("contents", []):
                        if "text" in content:
                            response_text += content["text"] + " "
        
        if not response_text.strip():
            return False, "No response text found to validate"
        
        # Basic grammar checks
        issues = []
        
        # Check for common grammar issues
        if " i " in response_text.lower():
            issues.append("Lowercase 'i' found (should be 'I')")
        
        # Check for sentence structure
        sentences = response_text.split('.')
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and not sentence[0].isupper():
                issues.append(f"Sentence doesn't start with capital letter: '{sentence[:30]}...'")
        
        if issues:
            return False, f"Grammar issues found: {'; '.join(issues[:3])}"
        
        return True, "Grammar validation passed"
        
    except Exception as e:
        return False, f"Grammar validation error: {str(e)}"
'''
            },
            {
                'name': 'Plagiarism Check',
                'description': 'Detects copied code or solutions from common sources',
                'validation': '''
def validate_plagiarism(data):
    """
    Check for potential plagiarism indicators.
    Returns (success: bool, message: str)
    """
    try:
        response_text = ""
        if "messages" in data:
            for message in data["messages"]:
                if message.get("role") == "assistant":
                    for content in message.get("contents", []):
                        if "text" in content:
                            response_text += content["text"] + " "
        
        if not response_text.strip():
            return False, "No response text found to validate"
        
        # Check for common plagiarism indicators
        plagiarism_indicators = [
            "stackoverflow.com",
            "github.com",
            "copy and paste",
            "copied from",
            "source: ",
            "reference: ",
        ]
        
        found_indicators = []
        for indicator in plagiarism_indicators:
            if indicator.lower() in response_text.lower():
                found_indicators.append(indicator)
        
        if found_indicators:
            return False, f"Potential plagiarism indicators found: {', '.join(found_indicators)}"
        
        return True, "Plagiarism check passed"
        
    except Exception as e:
        return False, f"Plagiarism validation error: {str(e)}"
'''
            },
            {
                'name': 'Code Style Check',
                'description': 'Ensures consistent formatting and naming conventions in code',
                'validation': '''
def validate_code_style(data):
    """
    Check for code style consistency.
    Returns (success: bool, message: str)
    """
    try:
        response_text = ""
        if "messages" in data:
            for message in data["messages"]:
                if message.get("role") == "assistant":
                    for content in message.get("contents", []):
                        if "text" in content:
                            response_text += content["text"] + " "
        
        if not response_text.strip():
            return False, "No response text found to validate"
        
        # Check for code blocks
        code_blocks = []
        lines = response_text.split('\\n')
        in_code_block = False
        current_block = []
        
        for line in lines:
            if '```' in line:
                if in_code_block:
                    code_blocks.append('\\n'.join(current_block))
                    current_block = []
                in_code_block = not in_code_block
            elif in_code_block:
                current_block.append(line)
        
        if not code_blocks:
            return True, "No code blocks found to validate"
        
        # Basic style checks
        style_issues = []
        for i, block in enumerate(code_blocks):
            # Check for consistent indentation
            lines = block.split('\\n')
            indentations = []
            for line in lines:
                if line.strip():
                    indent = len(line) - len(line.lstrip())
                    if indent > 0:
                        indentations.append(indent)
            
            if indentations and len(set(indentations)) > 3:
                style_issues.append(f"Inconsistent indentation in code block {i+1}")
        
        if style_issues:
            return False, f"Code style issues: {'; '.join(style_issues)}"
        
        return True, "Code style validation passed"
        
    except Exception as e:
        return False, f"Code style validation error: {str(e)}"
'''
            },
            {
                'name': 'Logic Validation',
                'description': 'Verifies the correctness of algorithmic approach and reasoning',
                'validation': '''
def validate_logic(data):
    """
    Check for logical consistency in the response.
    Returns (success: bool, message: str)
    """
    try:
        reasoning_steps = []
        if "messages" in data:
            for message in data["messages"]:
                if message.get("role") == "assistant" and "reasoning" in message:
                    process = message["reasoning"].get("process", [])
                    for step in process:
                        if "thoughts" in step:
                            for thought in step["thoughts"]:
                                reasoning_steps.append(thought.get("text", ""))
        
        if not reasoning_steps:
            return False, "No reasoning steps found to validate"
        
        # Check for logical flow
        logic_issues = []
        
        # Check for contradictions
        for i, step in enumerate(reasoning_steps):
            step_lower = step.lower()
            if "however" in step_lower and "but" in step_lower:
                logic_issues.append(f"Potential contradiction in step {i+1}")
        
        # Check for conclusion
        has_conclusion = any("therefore" in step.lower() or "conclusion" in step.lower() 
                           for step in reasoning_steps)
        
        if not has_conclusion:
            logic_issues.append("No clear conclusion found in reasoning")
        
        if logic_issues:
            return False, f"Logic issues found: {'; '.join(logic_issues)}"
        
        return True, "Logic validation passed"
        
    except Exception as e:
        return False, f"Logic validation error: {str(e)}"
'''
            },
            {
                'name': 'Performance Analysis',
                'description': 'Checks for efficiency and optimization considerations',
                'validation': '''
def validate_performance(data):
    """
    Check for performance considerations in the response.
    Returns (success: bool, message: str)
    """
    try:
        response_text = ""
        if "messages" in data:
            for message in data["messages"]:
                if message.get("role") == "assistant":
                    for content in message.get("contents", []):
                        if "text" in content:
                            response_text += content["text"] + " "
        
        if not response_text.strip():
            return False, "No response text found to validate"
        
        # Check for performance-related keywords
        performance_keywords = [
            "time complexity",
            "space complexity",
            "big o",
            "optimization",
            "efficient",
            "performance",
            "scalability"
        ]
        
        found_keywords = []
        for keyword in performance_keywords:
            if keyword.lower() in response_text.lower():
                found_keywords.append(keyword)
        
        if not found_keywords:
            return False, "No performance analysis found in response"
        
        return True, f"Performance analysis found: {', '.join(found_keywords)}"
        
    except Exception as e:
        return False, f"Performance validation error: {str(e)}"
'''
            },
            {
                'name': 'Security Review',
                'description': 'Identifies potential security vulnerabilities in code',
                'validation': '''
def validate_security(data):
    """
    Check for security considerations in the response.
    Returns (success: bool, message: str)
    """
    try:
        response_text = ""
        if "messages" in data:
            for message in data["messages"]:
                if message.get("role") == "assistant":
                    for content in message.get("contents", []):
                        if "text" in content:
                            response_text += content["text"] + " "
        
        if not response_text.strip():
            return False, "No response text found to validate"
        
        # Check for security vulnerabilities
        security_issues = []
        
        # Check for dangerous patterns
        dangerous_patterns = [
            "eval(",
            "exec(",
            "system(",
            "shell_exec",
            "password",
            "secret",
            "api_key"
        ]
        
        for pattern in dangerous_patterns:
            if pattern.lower() in response_text.lower():
                security_issues.append(f"Potential security issue: {pattern}")
        
        # Check for security best practices
        security_keywords = [
            "sanitize",
            "validate",
            "escape",
            "authentication",
            "authorization",
            "encryption"
        ]
        
        found_security = []
        for keyword in security_keywords:
            if keyword.lower() in response_text.lower():
                found_security.append(keyword)
        
        if security_issues:
            return False, f"Security issues found: {'; '.join(security_issues)}"
        
        if found_security:
            return True, f"Security considerations found: {', '.join(found_security)}"
        
        return True, "Basic security validation passed"
        
    except Exception as e:
        return False, f"Security validation error: {str(e)}"
'''
            }
        ]

        created_count = 0
        for validation_data in validations:
            validation, created = Validation.objects.get_or_create(
                name=validation_data['name'],
                defaults={
                    'description': validation_data['description'],
                    'validation': validation_data['validation'],
                    'is_active': True
                }
            )
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Created validation: {validation.name}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Validation already exists: {validation.name}')
                )

        self.stdout.write(
            self.style.SUCCESS(f'Successfully created {created_count} new validation criteria')
        )
