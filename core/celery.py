import os
from celery import Celery
from django.conf import settings

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

app = Celery('ai_document_processor')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Celery beat schedule for periodic tasks
app.conf.beat_schedule = {
    'cleanup-failed-jobs': {
        'task': 'documents.tasks.cleanup_failed_jobs',
        'schedule': 3600.0,  # Run every hour
    },
    'cleanup-old-logs': {
        'task': 'documents.tasks.cleanup_old_logs',
        'schedule': 86400.0,  # Run daily
    },
}

app.conf.timezone = 'UTC'

# Task execution configuration
app.conf.task_annotations = {
    'documents.tasks.process_document': {
        'rate_limit': '10/m',  # 10 tasks per minute
        'time_limit': 1800,    # 30 minutes
        'soft_time_limit': 1500,  # 25 minutes
    },
    'documents.tasks.analyze_with_gemini': {
        'rate_limit': '5/m',   # 5 AI requests per minute
        'time_limit': 600,     # 10 minutes
        'soft_time_limit': 540,   # 9 minutes
    },
}

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
