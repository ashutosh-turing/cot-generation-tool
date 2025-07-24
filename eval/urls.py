from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .views_auth import TuringDomainLoginView
from . import api_views
from eval.views import save_user_preferences
from . import api
from . import api_llm
from . import response_editor

urlpatterns = [
    path('modal_playground/', views.modal_playground, name='modal_playground'),
    path('trainer/task/edit/<int:task_id>/', views.edit_trainer_task, name='edit_trainer_task'),
    path('review/<path:question_id>/', views.review_question, name='review_question'),
    path('task-sync/', views.task_sync_config_view, name='task_sync_config'),
    path('project-config/', views.project_config_view, name='project_config'),
    path('dashboard/tasks/', views.trainer_dashboard, name='trainer_dashboard'),
    path('reviewer/', views.reviewer_dashboard, name='reviewer_dashboard'),
    path('trainer/question/<int:project_id>/<path:question_id>/', views.trainer_question_analysis, name='trainer_question_analysis'),
    path('', views.index, name='index'),
    path('convert_jsons/', views.convert_jsons, name='convert_jsons'),
    path('convert/', views.convert_to_json, name='convert_to_json'),
    path('upload/', views.upload_file, name='upload'),
    path('delete_file/<str:filename>/', views.delete_file, name='delete_file'),
    path('delete-all/', views.delete_all_files, name='delete_all_files'),
    path('validation_check/', views.validation_check, name='validation_check'),
    path('perform_validation/', views.perform_validation, name='perform_validation'),
    path('logical_checks/', views.logical_checks, name='logical_checks'),
    path('perform-logical-analysis/', views.perform_logical_analysis, name='perform_logical_analysis'),
    path('delete-all-converted-jsons/', views.delete_all_converted_jsons, name='delete_all_converted_jsons'),
    path('bulk-upload/', views.bulk_upload, name='bulk_upload'),
    path('model_evaluation/', views.model_evaluation, name='model_evaluation'),
    path('evaluate_models/', views.evaluate_models, name='evaluate_models'),
    path('get_model_results/<str:session_id>/', views.get_model_results, name='get_model_results'),
    path('reports/', views.reports, name='reports'),
    path('api/reports/all/', views.api_all_reports, name='api_all_reports'),
    # Custom login view with domain restriction
    path('accounts/login/', TuringDomainLoginView.as_view(), name='login'),
    # Django built-in logout view
    path('accounts/logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('save_to_history/', views.save_to_history, name='save_to_history'),
    path('get_evaluation_history/', views.get_evaluation_history, name='get_evaluation_history'),
    path('get_model_analytics/', views.get_model_analytics, name='get_model_analytics'),
    path('get_user_analytics/', views.get_user_analytics, name='get_user_analytics'),
    path('save_edited_response/', response_editor.save_edited_response, name='save_edited_response'),
    path('save_user_preferences/', save_user_preferences, name='save_user_preferences'),
    path('ground_truth/', views.ground_truth, name='ground_truth'),
    
    # API endpoints
    path('api/fetch-colab-content/', api_views.fetch_colab_content, name='api_fetch_colab_content'),
    path('api/transfer-to-colab/', api_views.transfer_to_colab, name='api_transfer_to_colab'),
    path('api/llm-models/', api.get_llm_models, name='api_llm_models'),
    path('api/models/', api.get_llm_models, name='api_models'),  # Added for compatibility with existing JS
    path('api/generate/', api.generate_response, name='api_generate'),
    path('api/validate/', api.validate_with_llm, name='api_validate'),
    path('api/review-colab/', api.review_colab, name='api_review_colab'),
    path('api/get-review-results/<str:job_id>/', api.get_review_results, name='get_review_results'),
    
    # New LLM Job API endpoints (Pub/Sub based with polling)
    path('api/llm/jobs/submit/', api_llm.submit_llm_job, name='api_submit_llm_job'),
    path('api/llm/jobs/<uuid:job_id>/status/', api_llm.poll_job_status, name='api_poll_job_status'),
    path('api/llm/jobs/<uuid:job_id>/result/', api_llm.get_job_result, name='api_get_job_result'),
    path('api/llm/jobs/', api_llm.list_user_jobs, name='api_list_user_jobs'),
    path('api/llm/jobs/stats/', views.get_llm_job_stats, name='api_get_llm_job_stats'),
    path('api/llm/trainer-analysis/', api_llm.submit_trainer_question_analysis, name='api_submit_trainer_analysis'),
    
    # Project configuration API (admin only)
    path('api/update_project_criteria/', views.update_project_criteria, name='update_project_criteria'),
    path('api/bulk_update_project_criteria/', views.bulk_update_project_criteria, name='bulk_update_project_criteria'),
    path('api/update_user_role/', views.update_user_role, name='update_user_role'),
    
    # Activity Tracking API endpoints
    path('api/activity/start/', views.activity_start, name='api_activity_start'),
    path('api/activity/update/', views.activity_update, name='api_activity_update'),
    path('api/activity/end/', views.activity_end, name='api_activity_end'),

    # Task Sync Status
    path('api/sync-status/', views.sync_status_api, name='api_sync_status'),
    
    # path('api/ground-truth-validate/', api_views.run_ground_truth_validation, name='api_ground_truth_validate'),
]
