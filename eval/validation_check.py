def check_json_structure(json_data):
    """Basic JSON structure validation"""
    required_fields = ['deliverable_id', 'messages', 'notes']
    for field in required_fields:
        if field not in json_data:
            return False, f"Missing required field: {field}"
    return True, "JSON structure is valid"

def check_messages_format(json_data):
    """Validate messages format"""
    try:
        messages = json_data.get('messages', [])
        if not isinstance(messages, list):
            return False, "Messages must be an array"
        
        for msg in messages:
            if 'role' not in msg:
                return False, "Message missing 'role' field"
            if 'contents' not in msg:
                return False, "Message missing 'contents' field"
        
        return True, "Messages format is valid"
    except Exception as e:
        return False, f"Error validating messages: {str(e)}"

def check_reasoning_process(json_data):
    """Validate reasoning process structure"""
    try:
        messages = json_data.get('messages', [])
        for msg in messages:
            if msg.get('role') == 'assistant':
                if 'reasoning' not in msg:
                    return False, "Assistant message missing reasoning"
                if 'process' not in msg['reasoning']:
                    return False, "Reasoning missing process"
                
                process = msg['reasoning']['process']
                if not isinstance(process, list):
                    return False, "Reasoning process must be an array"
                
                for section in process:
                    if 'summary' not in section:
                        return False, "Section missing summary"
                    if 'thoughts' not in section:
                        return False, "Section missing thoughts"
        
        return True, "Reasoning process structure is valid"
    except Exception as e:
        return False, f"Error validating reasoning process: {str(e)}"
