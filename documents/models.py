import os
import uuid
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator
from django.conf import settings


def document_upload_path(instance, filename):
    """Generate upload path for documents"""
    ext = filename.split('.')[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    return os.path.join('documents', str(instance.user.id), filename)


class Document(models.Model):
    """Model for uploaded documents"""
    
    STATUS_CHOICES = [
        ('uploaded', 'Uploaded'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    FILE_TYPE_CHOICES = [
        ('pdf', 'PDF'),
        ('txt', 'Text'),
        ('docx', 'Word Document'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=255)
    file = models.FileField(
        upload_to=document_upload_path,
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'txt', 'docx'])]
    )
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    file_size = models.PositiveIntegerField(help_text="File size in bytes")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploaded')
    
    # Processing metadata
    extracted_text = models.TextField(blank=True, null=True)
    processing_started_at = models.DateTimeField(blank=True, null=True)
    processing_completed_at = models.DateTimeField(blank=True, null=True)
    processing_error = models.TextField(blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.user.username})"
    
    @property
    def file_size_mb(self):
        """Return file size in MB"""
        return round(self.file_size / (1024 * 1024), 2)
    
    def save(self, *args, **kwargs):
        if self.file:
            # Set file type based on extension
            ext = self.file.name.split('.')[-1].lower()
            self.file_type = ext
            
            # Set file size
            if hasattr(self.file, 'size'):
                self.file_size = self.file.size
        
        super().save(*args, **kwargs)


class ProcessingJob(models.Model):
    """Model to track document processing jobs"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('started', 'Started'),
        ('progress', 'In Progress'),
        ('success', 'Success'),
        ('failure', 'Failure'),
        ('retry', 'Retry'),
        ('revoked', 'Revoked'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.OneToOneField(Document, on_delete=models.CASCADE, related_name='processing_job')
    celery_task_id = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    progress = models.PositiveIntegerField(default=0, help_text="Progress percentage (0-100)")
    
    # Task metadata
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    retry_count = models.PositiveIntegerField(default=0)
    
    # Processing steps tracking
    text_extraction_completed = models.BooleanField(default=False)
    ai_analysis_completed = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['celery_task_id']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"Processing Job for {self.document.title}"


class DocumentAnalysis(models.Model):
    """Single analysis record per document with all analysis types"""
    
    SENTIMENT_CHOICES = [
        ('positive', 'Positive'),
        ('negative', 'Negative'),
        ('neutral', 'Neutral'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.OneToOneField(Document, on_delete=models.CASCADE, related_name='analysis')
    
    # Analysis Results - Each as separate fields
    summary = models.TextField(blank=True, null=True, help_text="Document summary")
    key_points = models.JSONField(blank=True, null=True, help_text="List of key points")
    sentiment = models.CharField(max_length=20, choices=SENTIMENT_CHOICES, blank=True, null=True)
    sentiment_score = models.FloatField(blank=True, null=True, help_text="Sentiment confidence score (0-1)")
    topics = models.JSONField(blank=True, null=True, help_text="List of identified topics")
    
    # AI model metadata (consolidated)
    model_used = models.CharField(max_length=100, default='gemini-pro')
    total_tokens_used = models.PositiveIntegerField(blank=True, null=True)
    total_processing_time = models.FloatField(blank=True, null=True, help_text="Total processing time in seconds")
    
    # Processing status for each analysis type
    summary_completed = models.BooleanField(default=False)
    key_points_completed = models.BooleanField(default=False)
    sentiment_completed = models.BooleanField(default=False)
    topics_completed = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['document']),
            models.Index(fields=['sentiment']),
        ]
    
    def __str__(self):
        return f"Analysis for {self.document.title}"
    
    @property
    def is_complete(self):
        """Check if all analysis types are completed"""
        return all([
            self.summary_completed,
            self.key_points_completed,
            self.sentiment_completed,
            self.topics_completed,
        ])
    
    @property
    def completion_percentage(self):
        """Get completion percentage of analysis"""
        completed = sum([
            self.summary_completed,
            self.key_points_completed,
            self.sentiment_completed,
            self.topics_completed,
        ])
        return (completed / 4) * 100


class DocumentTag(models.Model):
    """Model for document tags/categories"""
    
    name = models.CharField(max_length=50, unique=True)
    color = models.CharField(max_length=7, default='#007bff', help_text="Hex color code")
    description = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


class DocumentTagging(models.Model):
    """Many-to-many relationship between documents and tags"""
    
    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    tag = models.ForeignKey(DocumentTag, on_delete=models.CASCADE)
    confidence = models.FloatField(default=1.0, help_text="Tag confidence (0-1)")
    auto_generated = models.BooleanField(default=False, help_text="Whether tag was auto-generated by AI")
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['document', 'tag']
        indexes = [
            models.Index(fields=['document']),
            models.Index(fields=['tag']),
        ]
    
    def __str__(self):
        return f"{self.document.title} - {self.tag.name}"


class ProcessingLog(models.Model):
    """Model to log processing steps and events"""
    
    LOG_LEVEL_CHOICES = [
        ('debug', 'Debug'),
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='processing_logs')
    processing_job = models.ForeignKey(
        ProcessingJob, 
        on_delete=models.CASCADE, 
        related_name='logs',
        blank=True, 
        null=True
    )
    
    level = models.CharField(max_length=10, choices=LOG_LEVEL_CHOICES, default='info')
    message = models.TextField()
    step = models.CharField(max_length=100, blank=True, help_text="Processing step name")
    metadata = models.JSONField(blank=True, null=True, help_text="Additional log metadata")
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['document', '-created_at']),
            models.Index(fields=['processing_job', '-created_at']),
            models.Index(fields=['level']),
        ]
    
    def __str__(self):
        return f"{self.level.upper()}: {self.message[:50]}..."
