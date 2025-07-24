from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Main dashboard routes
    path('', views.index, name='index'),
    
    # Dashboard routes by role
    path('dashboard/tasks/', views.trainer_dashboard, name='trainer_dashboard'),
    path('reviewer/', views.reviewer_dashboard, name='reviewer_dashboard'),
    
    # Task management
    path('trainer-question-analysis/<str:project_id>/<str:question_id>/', views.trainer_question_analysis, name='trainer_question_analysis'),
    path('edit-trainer-task/<int:task_id>/', views.edit_trainer_task, name='edit_trainer_task'),
    path('review/<str:question_id>/', views.review_question, name='review_question'),
    
    # Configuration views (admin only)
    path('task-sync/', views.task_sync_config_view, name='task_sync_config'),
    path('project-config/', views.project_config_view, name='project_config'),
    
    # File management
    path('convert_jsons/', views.convert_jsons, name='convert_jsons'),
    path('upload/', views.upload_file, name='upload_file'),
    path('delete/<str:filename>/', views.delete_file, name='delete_file'),
    path('delete_all/', views.delete_all_files, name='delete_all_files'),
    path('bulk_upload/', views.bulk_upload, name='bulk_upload'),
    path('convert_to_json/', views.convert_to_json, name='convert_to_json'),
    path('delete_all_converted_jsons/', views.delete_all_converted_jsons, name='delete_all_converted_jsons'),
    
    # Validation and analysis
    path('validation_check/', views.validation_check, name='validation_check'),
    path('perform_validation/', views.perform_validation, name='perform_validation'),
    path('logical_checks/', views.logical_checks, name='logical_checks'),
    path('perform_logical_analysis/', views.perform_logical_analysis, name='perform_logical_analysis'),
    path('ground_truth/', views.ground_truth, name='ground_truth'),
    
    # Model evaluation
    path('model_evaluation/', views.model_evaluation, name='model_evaluation'),
    path('evaluate_models/', views.evaluate_models, name='evaluate_models'),
    path('get_model_results/<str:session_id>/', views.get_model_results, name='get_model_results'),
    path('save_to_history/', views.save_to_history, name='save_to_history'),
    path('get_evaluation_history/', views.get_evaluation_history, name='get_evaluation_history'),
    path('save_edited_response/', views.save_edited_response, name='save_edited_response'),
    
    # Modal playground
    path('modal_playground/', views.modal_playground, name='modal_playground'),
    
    # Reports and analytics
    path('reports/', views.reports, name='reports'),
    path('api/all_reports/', views.api_all_reports, name='api_all_reports'),
    path('get_model_analytics/', views.get_model_analytics, name='get_model_analytics'),
    path('get_user_analytics/', views.get_user_analytics, name='get_user_analytics'),
    path('get_llm_job_stats/', views.get_llm_job_stats, name='get_llm_job_stats'),
    
    # User preferences
    path('save_user_preferences/', views.save_user_preferences, name='save_user_preferences'),
    
    # API endpoints
    path('get_llm_models/', views.get_llm_models, name='get_llm_models'),
    path('api/llm-models/', views.get_llm_models, name='api_llm_models'),
    path('api/sync-status/', views.sync_status_api, name='sync_status_api'),
    
    # Project configuration API (admin only)
    path('api/update_project_criteria/', views.update_project_criteria, name='update_project_criteria'),
    path('api/bulk_update_project_criteria/', views.bulk_update_project_criteria, name='bulk_update_project_criteria'),
    path('api/update_user_role/', views.update_user_role, name='update_user_role'),
    
    # Activity tracking API endpoints
    path('api/activity/start/', views.activity_start, name='activity_start'),
    path('api/activity/update/', views.activity_update, name='activity_update'),
    path('api/activity/end/', views.activity_end, name='activity_end'),
    
    # Authentication URLs
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
