from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import (
    Document, ProcessingJob, DocumentAnalysis, 
    DocumentTag, DocumentTagging, ProcessingLog
)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    """Admin interface for Document model"""
    
    list_display = [
        'title', 'user', 'file_type', 'status', 
        'file_size_display', 'created_at', 'processing_actions'
    ]
    list_filter = ['status', 'file_type', 'created_at', 'user']
    search_fields = ['title', 'user__username', 'user__email']
    readonly_fields = [
        'id', 'file_type', 'file_size', 'extracted_text',
        'processing_started_at', 'processing_completed_at',
        'created_at', 'updated_at'
    ]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'user', 'title', 'file', 'file_type', 'file_size')
        }),
        ('Processing Status', {
            'fields': ('status', 'processing_started_at', 'processing_completed_at', 'processing_error')
        }),
        ('Extracted Content', {
            'fields': ('extracted_text',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def file_size_display(self, obj):
        """Display file size in human readable format"""
        if obj.file_size:
            return f"{obj.file_size_mb} MB"
        return "N/A"
    file_size_display.short_description = "File Size"
    
    def processing_actions(self, obj):
        """Display processing action buttons"""
        if obj.status == 'processing':
            return format_html(
                '<span style="color: orange;">Processing...</span>'
            )
        elif obj.status == 'completed':
            try:
                analysis = obj.analysis
                analysis_url = reverse('admin:documents_documentanalysis_change', args=[analysis.id])
                return format_html(
                    '<a href="{}" class="button">View Analysis</a>',
                    analysis_url
                )
            except DocumentAnalysis.DoesNotExist:
                return format_html('<span style="color: gray;">No Analysis</span>')
        elif obj.status == 'failed':
            return format_html(
                '<span style="color: red;">Failed</span>'
            )
        return format_html(
            '<span style="color: gray;">Uploaded</span>'
        )
    processing_actions.short_description = "Actions"
    
    def get_queryset(self, request):
        """Optimize queryset with select_related"""
        return super().get_queryset(request).select_related('user')


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    """Admin interface for ProcessingJob model"""
    
    list_display = [
        'document_title', 'status', 'progress', 
        'started_at', 'completed_at', 'retry_count'
    ]
    list_filter = ['status', 'created_at', 'started_at']
    search_fields = ['document__title', 'document__user__username']
    readonly_fields = [
        'id', 'celery_task_id', 'created_at', 'updated_at'
    ]
    
    fieldsets = (
        ('Job Information', {
            'fields': ('id', 'document', 'celery_task_id', 'status', 'progress')
        }),
        ('Timing', {
            'fields': ('started_at', 'completed_at', 'retry_count')
        }),
        ('Progress Tracking', {
            'fields': ('text_extraction_completed', 'ai_analysis_completed')
        }),
        ('Error Information', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def document_title(self, obj):
        """Display document title with link"""
        url = reverse('admin:documents_document_change', args=[obj.document.id])
        return format_html('<a href="{}">{}</a>', url, obj.document.title)
    document_title.short_description = "Document"
    
    def get_queryset(self, request):
        """Optimize queryset with select_related"""
        return super().get_queryset(request).select_related('document', 'document__user')


@admin.register(DocumentAnalysis)
class DocumentAnalysisAdmin(admin.ModelAdmin):
    """Admin interface for DocumentAnalysis model"""
    
    list_display = [
        'document_title', 'completion_status', 'model_used',
        'total_processing_time', 'total_tokens_used', 'created_at'
    ]
    list_filter = ['model_used', 'created_at', 'sentiment']
    search_fields = ['document__title', 'document__user__username']
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Analysis Information', {
            'fields': ('id', 'document', 'model_used')
        }),
        ('Analysis Results', {
            'fields': ('summary', 'key_points', 'sentiment', 'sentiment_score', 'topics')
        }),
        ('Processing Status', {
            'fields': ('summary_completed', 'key_points_completed', 'sentiment_completed', 'topics_completed')
        }),
        ('Model Information', {
            'fields': ('total_tokens_used', 'total_processing_time')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def document_title(self, obj):
        """Display document title with link"""
        url = reverse('admin:documents_document_change', args=[obj.document.id])
        return format_html('<a href="{}">{}</a>', url, obj.document.title)
    document_title.short_description = "Document"
    
    def completion_status(self, obj):
        """Display completion status with progress"""
        percentage = obj.completion_percentage
        if percentage == 100:
            return format_html('<span style="color: green;">Complete ({}%)</span>', percentage)
        elif percentage > 0:
            return format_html('<span style="color: orange;">In Progress ({}%)</span>', percentage)
        else:
            return format_html('<span style="color: gray;">Not Started</span>')
    completion_status.short_description = "Status"
    
    def get_queryset(self, request):
        """Optimize queryset with select_related"""
        return super().get_queryset(request).select_related('document', 'document__user')


@admin.register(DocumentTag)
class DocumentTagAdmin(admin.ModelAdmin):
    """Admin interface for DocumentTag model"""
    
    list_display = ['name', 'color_display', 'document_count', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at']
    
    def color_display(self, obj):
        """Display color as colored box"""
        return format_html(
            '<div style="width: 20px; height: 20px; background-color: {}; border: 1px solid #ccc;"></div>',
            obj.color
        )
    color_display.short_description = "Color"
    
    def document_count(self, obj):
        """Display count of documents with this tag"""
        count = obj.documenttagging_set.count()
        if count > 0:
            url = reverse('admin:documents_documenttagging_changelist') + f'?tag__id__exact={obj.id}'
            return format_html('<a href="{}">{} documents</a>', url, count)
        return "0 documents"
    document_count.short_description = "Documents"


@admin.register(DocumentTagging)
class DocumentTaggingAdmin(admin.ModelAdmin):
    """Admin interface for DocumentTagging model"""
    
    list_display = ['document_title', 'tag', 'confidence', 'auto_generated', 'created_at']
    list_filter = ['auto_generated', 'created_at', 'tag']
    search_fields = ['document__title', 'tag__name']
    
    def document_title(self, obj):
        """Display document title with link"""
        url = reverse('admin:documents_document_change', args=[obj.document.id])
        return format_html('<a href="{}">{}</a>', url, obj.document.title)
    document_title.short_description = "Document"


@admin.register(ProcessingLog)
class ProcessingLogAdmin(admin.ModelAdmin):
    """Admin interface for ProcessingLog model"""
    
    list_display = ['document_title', 'level', 'step', 'message_preview', 'created_at']
    list_filter = ['level', 'step', 'created_at']
    search_fields = ['document__title', 'message', 'step']
    readonly_fields = ['id', 'created_at']
    
    fieldsets = (
        ('Log Information', {
            'fields': ('id', 'document', 'processing_job', 'level', 'step')
        }),
        ('Message', {
            'fields': ('message',)
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
        ('Timestamp', {
            'fields': ('created_at',)
        }),
    )
    
    def document_title(self, obj):
        """Display document title with link"""
        url = reverse('admin:documents_document_change', args=[obj.document.id])
        return format_html('<a href="{}">{}</a>', url, obj.document.title)
    document_title.short_description = "Document"
    
    def message_preview(self, obj):
        """Display truncated message"""
        if len(obj.message) > 50:
            return obj.message[:50] + "..."
        return obj.message
    message_preview.short_description = "Message"
    
    def get_queryset(self, request):
        """Optimize queryset with select_related"""
        return super().get_queryset(request).select_related(
            'document', 'document__user', 'processing_job'
        )


# Customize admin site
admin.site.site_header = "AI Document Processor Administration"
admin.site.site_title = "AI Document Processor Admin"
admin.site.index_title = "Welcome to AI Document Processor Administration"
