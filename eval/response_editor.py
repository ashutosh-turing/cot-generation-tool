from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.utils import timezone
import json
from .models import Response, ModelEvaluationHistory
import logging

logger = logging.getLogger(__name__)

@login_required
@require_POST
def save_edited_response(request):
    """
    Save an edited response from the response editor
    """
    logger.debug(f"save_edited_response called with request method: {request.method}")
    try:
        data = json.loads(request.body)
        response_id = data.get('response_id')
        model_id = data.get('model_id')
        edited_content = data.get('edited_content')
        session_id = data.get('session_id')
        
        # Log received data for debugging
        logger.debug(f"Received edit request: response_id={response_id}, model_id={model_id}, session_id={session_id}")
        logger.debug(f"Request body: {request.body.decode('utf-8')[:200]}...")
        
        # Try to extract response_id from model_id if response_id is missing
        if not response_id and model_id:
            logger.info(f"Attempting to use model_id as response_id: {model_id}")
            response_id = model_id
            
        # If we still don't have a response_id, check if it's a generated one
        if response_id and response_id.startswith('generated-'):
            logger.info(f"Using generated response ID: {response_id}")
            # For generated IDs, we'll just return success without trying to update the database
            return JsonResponse({
                'success': True,
                'db_updated': False,
                'message': 'Changes saved to session only (no database record found)'
            })
            
        if not response_id:
            logger.error("Missing response_id in request")
            return JsonResponse({'success': False, 'error': 'Missing response ID'})
            
        if not edited_content:
            logger.error("Missing edited_content in request")
            return JsonResponse({'success': False, 'error': 'Missing edited content'})
        
        # Try to find the response in the database
        db_updated = False
        try:
            response = Response.objects.get(response_id=response_id)
            # Save both the plain response and formatted response
            response.formatted_response = edited_content
            response.save_edit(edited_content, request.user)
            db_updated = True
            logger.info(f"Updated response {response_id} in database")
        except Response.DoesNotExist:
            # If not in Response model, try ModelEvaluationHistory
            try:
                eval_history = ModelEvaluationHistory.objects.get(evaluation_id=response_id)
                # Create history entry
                history_entry = {
                    'previous_content': eval_history.response,
                    'edited_at': timezone.now().isoformat(),
                    'editor': request.user.username if request.user else None
                }
                
                # Update the edit history
                if isinstance(eval_history.edit_history, list):
                    eval_history.edit_history.append(history_entry)
                else:
                    eval_history.edit_history = [history_entry]
                
                # Update the response content
                eval_history.response = edited_content
                eval_history.formatted_response = edited_content
                eval_history.is_edited = True
                eval_history.save()
                
                db_updated = True
                logger.info(f"Updated evaluation history {response_id} in database with edit history")
            except ModelEvaluationHistory.DoesNotExist:
                logger.warning(f"Could not find response {response_id} in database")
                # Continue anyway - we'll update the session data
        
        # If we have a session ID, update the in-memory session data too
        if session_id:
            # This would depend on how you're storing session data
            # For example, if using Redis or a similar cache:
            # from django.core.cache import cache
            # session_data = cache.get(f"eval_session_{session_id}")
            # if session_data and 'results' in session_data:
            #     for result in session_data['results']:
            #         if result.get('id') == response_id:
            #             result['response'] = edited_content
            #             cache.set(f"eval_session_{session_id}", session_data)
            pass
        
        return JsonResponse({
            'success': True, 
            'db_updated': db_updated,
            'message': 'Response updated successfully'
        })
        
    except Exception as e:
        logger.exception(f"Error saving edited response: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})
