from datetime import datetime
import queue

log_queue = queue.Queue()

def log_message(message):
    if not message:
        return
        
    log_queue.put({
        'message': str(message),  # Ensure message is a string
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'type': 'log'
    })
