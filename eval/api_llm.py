from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
import json
import logging
from django.contrib.auth.models import User
from eval.models import LLMModel, LLMJob, ProjectLLMModel, TrainerTask
from eval.utils.pubsub import publish_message
import uuid
from eval.utils.logger import log

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["POST"])
def submit_llm_job(request):
    """
    API endpoint to submit an LLM processing job to Pub/Sub queue.
    Returns a job_id that can be used for polling.
    
    Expected JSON payload:
    {
        "job_type": "trainer_question_analysis" | "review_colab" | "general_llm_request",
        "model_id": "uuid-of-llm-model",
        "input_data": {
            // Job-specific input parameters
        },
        "question_id": "optional-question-id"
    }
    """
    try:
        data = json.loads(request.body)
        job_type = data.get('job_type')
        model_id = data.get('model_id')
        input_data = data.get('input_data', {})
        question_id = data.get('question_id')

        task = TrainerTask.objects.filter(question_id=question_id).first()
        project_models = ProjectLLMModel.objects.filter(project_id=task.project) if task.project else ProjectLLMModel.objects.none()
        
        if not job_type or not model_id:
            return JsonResponse({
                "success": False,
                "error": "Missing required parameters: job_type or model_id"
            }, status=400)
        
        # Validate job_type
        valid_job_types = [choice[0] for choice in LLMJob.JOB_TYPE_CHOICES]
        if job_type not in valid_job_types:
            return JsonResponse({
                "success": False,
                "error": f"Invalid job_type. Must be one of: {valid_job_types}"
            }, status=400)
        
        # Validate model exists
        try:
            model = None
            if project_models.exists():
                project_model_instance = project_models.filter(llm_model_id=model_id, is_active=True).select_related('llm_model').first()
                if not project_model_instance:
                    raise LLMModel.DoesNotExist
                model = project_model_instance.llm_model
            else:
                # No overrides defined for project — fallback to global model
                model = LLMModel.objects.get(id=model_id, is_active=True) 
            if model is None:
                raise LLMModel.DoesNotExist
                
        except LLMModel.DoesNotExist:
            return JsonResponse({
                "success": False,
                "error": f"LLM model with id {model_id} not found or inactive"
            }, status=400)
        
        # Create job record in database
        job = LLMJob.objects.create(
            job_type=job_type,
            user=request.user if request.user.is_authenticated else None,
            model=model,
            input_data=input_data,
            question_id=question_id
        )
        
        # Prepare data for Pub/Sub
        pubsub_data = {
            "type": job_type,
            "job_id": str(job.job_id),
            "model_id": model_id,
            "user_id": request.user.id if request.user.is_authenticated else None,
            "question_id": question_id,
            **input_data  # Merge input_data into the message
        }
        
        # Publish to Pub/Sub
        publish_message(pubsub_data)
        
        logger.info(f"Submitted {job_type} job {job.job_id} for model {model.name}")
        
        return JsonResponse({
            "success": True,
            "job_id": str(job.job_id),
            "status": job.status,
            "message": f"Job submitted successfully. Use job_id to poll for results."
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            "success": False,
            "error": "Invalid JSON in request body"
        }, status=400)
    except Exception as e:
        logger.error(f"Error submitting LLM job: {str(e)}")
        return JsonResponse({
            "success": False,
            "error": f"Internal server error: {str(e)}"
        }, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def poll_job_status(request, job_id):
    """
    API endpoint to poll for job status and results.
    
    GET /api/llm/jobs/{job_id}/status/
    
    Returns:
    {
        "success": true,
        "job_id": "uuid",
        "status": "pending|processing|completed|failed",
        "is_complete": boolean,
        "result_data": {...},  // Only if completed
        "error_message": "...", // Only if failed
        "created_at": "timestamp",
        "processing_time": seconds // Only if completed
    }
    """
    try:
        try:
            job = LLMJob.objects.get(job_id=job_id)
        except LLMJob.DoesNotExist:
            return JsonResponse({
                "success": False,
                "error": f"Job with id {job_id} not found"
            }, status=404)
        
        # Check if user has permission to view this job
        if job.user and request.user != job.user and not request.user.is_staff:
            return JsonResponse({
                "success": False,
                "error": "Permission denied"
            }, status=403)
        
        response_data = {
            "success": True,
            "job_id": str(job.job_id),
            "job_type": job.job_type,
            "status": job.status,
            "is_complete": job.is_complete,
            "created_at": job.created_at.isoformat(),
        }
        
        # Add model information
        if job.model:
            response_data["model"] = {
                "id": str(job.model.id),
                "name": job.model.name,
                "provider": job.model.provider
            }
        
        # Add timing information
        if job.started_at:
            response_data["started_at"] = job.started_at.isoformat()
        if job.completed_at:
            response_data["completed_at"] = job.completed_at.isoformat()
        if job.processing_time:
            response_data["processing_time"] = job.processing_time
        
        # Add results if completed
        if job.status == 'completed':
            response_data["result_data"] = job.result_data
        
        # Add error message if failed
        if job.status == 'failed':
            response_data["error_message"] = job.error_message
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Error polling job status: {str(e)}")
        return JsonResponse({
            "success": False,
            "error": f"Internal server error: {str(e)}"
        }, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def get_job_result(request, job_id):
    """
    API endpoint to retrieve the final result of a completed job.
    This is the optional endpoint mentioned in requirement #3.
    
    GET /api/llm/jobs/{job_id}/result/
    
    Returns:
    {
        "success": true,
        "job_id": "uuid",
        "job_type": "trainer_question_analysis",
        "status": "completed",
        "result_data": {...},
        "processing_time": seconds,
        "model": {...}
    }
    """
    try:
        try:
            job = LLMJob.objects.get(job_id=job_id)
        except LLMJob.DoesNotExist:
            return JsonResponse({
                "success": False,
                "error": f"Job with id {job_id} not found"
            }, status=404)
        
        # Check if user has permission to view this job
        if job.user and request.user != job.user and not request.user.is_staff:
            return JsonResponse({
                "success": False,
                "error": "Permission denied"
            }, status=403)
        
        # Check if job is completed
        if job.status != 'completed':
            return JsonResponse({
                "success": False,
                "error": f"Job is not completed yet. Current status: {job.status}",
                "status": job.status,
                "is_complete": job.is_complete
            }, status=400)
        
        response_data = {
            "success": True,
            "job_id": str(job.job_id),
            "job_type": job.job_type,
            "status": job.status,
            "result_data": job.result_data,
            "created_at": job.created_at.isoformat(),
            "completed_at": job.completed_at.isoformat(),
            "processing_time": job.processing_time
        }
        
        # Add model information
        if job.model:
            response_data["model"] = {
                "id": str(job.model.id),
                "name": job.model.name,
                "provider": job.model.provider
            }
        
        # Add question_id if available
        if job.question_id:
            response_data["question_id"] = job.question_id
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Error getting job result: {str(e)}")
        return JsonResponse({
            "success": False,
            "error": f"Internal server error: {str(e)}"
        }, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def list_user_jobs(request):
    """
    API endpoint to list jobs for the current user.
    
    GET /api/llm/jobs/?status=pending&job_type=trainer_question_analysis&limit=10
    
    Query parameters:
    - status: Filter by status (optional)
    - job_type: Filter by job type (optional)
    - limit: Number of results to return (default: 20, max: 100)
    - offset: Offset for pagination (default: 0)
    """
    try:
        if not request.user.is_authenticated:
            return JsonResponse({
                "success": False,
                "error": "Authentication required"
            }, status=401)
        
        # Get query parameters
        status_filter = request.GET.get('status')
        job_type_filter = request.GET.get('job_type')
        limit = min(int(request.GET.get('limit', 20)), 100)
        offset = int(request.GET.get('offset', 0))
        
        # Build query
        queryset = LLMJob.objects.filter(user=request.user)
        
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if job_type_filter:
            queryset = queryset.filter(job_type=job_type_filter)
        
        # Get total count
        total_count = queryset.count()
        
        # Apply pagination
        jobs = queryset[offset:offset + limit]
        
        # Serialize jobs
        jobs_data = []
        for job in jobs:
            job_data = {
                "job_id": str(job.job_id),
                "job_type": job.job_type,
                "status": job.status,
                "is_complete": job.is_complete,
                "created_at": job.created_at.isoformat(),
                "question_id": job.question_id
            }
            
            if job.model:
                job_data["model"] = {
                    "id": str(job.model.id),
                    "name": job.model.name,
                    "provider": job.model.provider
                }
            
            if job.completed_at:
                job_data["completed_at"] = job.completed_at.isoformat()
                job_data["processing_time"] = job.processing_time
            
            jobs_data.append(job_data)
        
        return JsonResponse({
            "success": True,
            "jobs": jobs_data,
            "pagination": {
                "total_count": total_count,
                "limit": limit,
                "offset": offset,
                "has_next": offset + limit < total_count
            }
        })
        
    except Exception as e:
        logger.error(f"Error listing user jobs: {str(e)}")
        return JsonResponse({
            "success": False,
            "error": f"Internal server error: {str(e)}"
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def submit_trainer_question_analysis(request):
    """
    Convenience endpoint specifically for trainer question analysis.
    This wraps the generic submit_llm_job endpoint with specific parameters.
    
    Expected JSON payload:
    {
        "model_id": "uuid-of-llm-model",
        "question_id": "question-identifier",
        "project_id": "project-identifier",
        "system_message": "system instructions",
        "full_input": "the full input text to analyze"
    }
    """
    try:
        data = json.loads(request.body)
        model_id = data.get('model_id')
        question_id = data.get('question_id')
        project_id = data.get('project_id')
        system_message = data.get('system_message', '')
        full_input = data.get('full_input')
        
        if not model_id or not full_input:
            return JsonResponse({
                "success": False,
                "error": "Missing required parameters: model_id or full_input"
            }, status=400)
        
        # Prepare input data for the job
        input_data = {
            "system_message": system_message,
            "full_input": full_input
        }
        
        # Create the job using the generic endpoint logic
        try:
            model = None
            # Check if project has any tied models at all
            project_models = ProjectLLMModel.objects.filter(project_id=project_id) if project_id else ProjectLLMModel.objects.none()

            if project_models.exists():
                # Must use a model from ProjectLLMModel — filter by id and active status
                project_model_instance = project_models.filter(llm_model_id=model_id, is_active=True).select_related('llm_model').first()
                if not project_model_instance:
                    raise LLMModel.DoesNotExist
                model = project_model_instance.llm_model
            else:
                # No overrides defined for project — fallback to global model
                model = LLMModel.objects.get(id=model_id, is_active=True)

        except LLMModel.DoesNotExist:
            return JsonResponse({
                "success": False,
                "error": f"LLM model with id {model_id} not found or inactive for this project"
            }, status=400)

        
        # Create job record
        job = LLMJob.objects.create(
            job_type='trainer_question_analysis',
            user=request.user if request.user.is_authenticated else None,
            model=model,
            input_data=input_data,
            question_id=question_id
        )
        
        # Prepare data for Pub/Sub
        pubsub_data = {
            "type": "trainer_question_analysis",
            "job_id": str(job.job_id),
            "model_id": model_id,
            "user_id": request.user.id if request.user.is_authenticated else None,
            "question_id": question_id,
            "system_message": system_message,
            "full_input": full_input
        }
        
        # Publish to Pub/Sub
        publish_message(pubsub_data)
        
        logger.info(f"Submitted trainer question analysis job {job.job_id} for question {question_id}")
        
        return JsonResponse({
            "success": True,
            "job_id": str(job.job_id),
            "status": job.status,
            "question_id": question_id,
            "message": "Trainer question analysis job submitted successfully. Use job_id to poll for results."
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            "success": False,
            "error": "Invalid JSON in request body"
        }, status=400)
    except Exception as e:
        logger.error(f"Error submitting trainer question analysis: {str(e)}")
        return JsonResponse({
            "success": False,
            "error": f"Internal server error: {str(e)}"
        }, status=500)
