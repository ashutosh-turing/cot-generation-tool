# LLM Job API Usage Examples

This document provides examples of how to use the new Google Pub/Sub based LLM processing API with polling endpoints.

## Overview

The new API design follows these principles:
1. **Submit jobs to Pub/Sub queue** - Jobs are processed asynchronously
2. **Poll for status** - Check if job is complete using polling endpoints
3. **Retrieve results** - Get final results once processing is complete

## API Endpoints

### 1. Submit LLM Job (Generic)
**POST** `/api/llm/jobs/submit/`

Submit any type of LLM processing job to the queue.

```json
{
    "job_type": "trainer_question_analysis",
    "model_id": "uuid-of-llm-model",
    "input_data": {
        "system_message": "You are a helpful assistant.",
        "full_input": "Analyze this question..."
    },
    "question_id": "optional-question-id"
}
```

**Response:**
```json
{
    "success": true,
    "job_id": "uuid-generated-job-id",
    "status": "pending",
    "message": "Job submitted successfully. Use job_id to poll for results."
}
```

### 2. Submit Trainer Question Analysis (Convenience)
**POST** `/api/llm/trainer-analysis/`

Convenience endpoint specifically for trainer question analysis.

```json
{
    "model_id": "uuid-of-llm-model",
    "question_id": "question-123",
    "system_message": "You are an expert code reviewer.",
    "full_input": "Please analyze this coding problem..."
}
```

### 3. Poll Job Status
**GET** `/api/llm/jobs/{job_id}/status/`

Poll to check if a job is complete and get results.

**Response (Pending):**
```json
{
    "success": true,
    "job_id": "uuid",
    "job_type": "trainer_question_analysis",
    "status": "pending",
    "is_complete": false,
    "created_at": "2025-01-18T10:15:30Z",
    "model": {
        "id": "model-uuid",
        "name": "GPT-4",
        "provider": "openai"
    }
}
```

**Response (Completed):**
```json
{
    "success": true,
    "job_id": "uuid",
    "job_type": "trainer_question_analysis",
    "status": "completed",
    "is_complete": true,
    "created_at": "2025-01-18T10:15:30Z",
    "started_at": "2025-01-18T10:15:35Z",
    "completed_at": "2025-01-18T10:16:45Z",
    "processing_time": 70.5,
    "result_data": {
        "success": true,
        "result": "The analysis shows..."
    },
    "model": {
        "id": "model-uuid",
        "name": "GPT-4",
        "provider": "openai"
    }
}
```

### 4. Get Job Result (Optional)
**GET** `/api/llm/jobs/{job_id}/result/`

Retrieve the final result of a completed job. This endpoint only works for completed jobs.

**Response:**
```json
{
    "success": true,
    "job_id": "uuid",
    "job_type": "trainer_question_analysis",
    "status": "completed",
    "result_data": {
        "success": true,
        "result": "The detailed analysis result..."
    },
    "processing_time": 70.5,
    "model": {
        "id": "model-uuid",
        "name": "GPT-4",
        "provider": "openai"
    },
    "question_id": "question-123"
}
```

### 5. List User Jobs
**GET** `/api/llm/jobs/?status=pending&job_type=trainer_question_analysis&limit=10`

List jobs for the current user with optional filtering.

**Query Parameters:**
- `status`: Filter by status (pending, processing, completed, failed)
- `job_type`: Filter by job type
- `limit`: Number of results (default: 20, max: 100)
- `offset`: Offset for pagination

## Usage Patterns

### Pattern 1: Submit and Poll
```javascript
// 1. Submit job
const submitResponse = await fetch('/api/llm/trainer-analysis/', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
    },
    body: JSON.stringify({
        model_id: 'model-uuid',
        question_id: 'question-123',
        system_message: 'You are a helpful assistant.',
        full_input: 'Analyze this problem...'
    })
});

const submitData = await submitResponse.json();
const jobId = submitData.job_id;

// 2. Poll for completion
const pollInterval = setInterval(async () => {
    const statusResponse = await fetch(`/api/llm/jobs/${jobId}/status/`);
    const statusData = await statusResponse.json();
    
    if (statusData.is_complete) {
        clearInterval(pollInterval);
        
        if (statusData.status === 'completed') {
            console.log('Job completed:', statusData.result_data);
        } else if (statusData.status === 'failed') {
            console.error('Job failed:', statusData.error_message);
        }
    }
}, 2000); // Poll every 2 seconds
```

### Pattern 2: Submit and Get Result Later
```javascript
// 1. Submit job
const submitResponse = await fetch('/api/llm/jobs/submit/', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
    },
    body: JSON.stringify({
        job_type: 'trainer_question_analysis',
        model_id: 'model-uuid',
        input_data: {
            system_message: 'You are a helpful assistant.',
            full_input: 'Analyze this problem...'
        },
        question_id: 'question-123'
    })
});

const submitData = await submitResponse.json();
const jobId = submitData.job_id;

// 2. Later, get the result (only works if job is completed)
const resultResponse = await fetch(`/api/llm/jobs/${jobId}/result/`);
const resultData = await resultResponse.json();

if (resultData.success) {
    console.log('Final result:', resultData.result_data);
}
```

## Job Types

Currently supported job types:
- `trainer_question_analysis`: Analyze trainer questions
- `review_colab`: Review Google Colab notebooks
- `general_llm_request`: Generic LLM requests

## Error Handling

All endpoints return consistent error responses:

```json
{
    "success": false,
    "error": "Error message describing what went wrong"
}
```

Common HTTP status codes:
- `200`: Success
- `400`: Bad request (missing parameters, invalid data)
- `401`: Authentication required
- `403`: Permission denied
- `404`: Job not found
- `500`: Internal server error

## Authentication

Most endpoints require user authentication. Make sure to include proper authentication headers or cookies when making requests.

## Backward Compatibility

The new API endpoints work alongside the existing cache-based system. The job processor stores results in both:
1. **Database** (new LLMJob model) - for the new polling API
2. **Cache** (Redis/memory) - for backward compatibility with existing code

This ensures existing functionality continues to work while providing the new polling-based interface.
