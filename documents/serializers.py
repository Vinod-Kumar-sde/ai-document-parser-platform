from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Document, ProcessingJob, DocumentAnalysis, DocumentTag, ProcessingLog


class DocumentSerializer(serializers.ModelSerializer):
    """Serializer for Document model"""
    
    file_size_mb = serializers.ReadOnlyField()
    processing_job = serializers.SerializerMethodField()
    analysis_results = serializers.SerializerMethodField()
    
    class Meta:
        model = Document
        fields = [
            'id', 'title', 'file', 'file_type', 'file_size', 'file_size_mb',
            'status', 'extracted_text', 'processing_started_at', 
            'processing_completed_at', 'processing_error', 'created_at', 
            'updated_at', 'processing_job', 'analysis_results'
        ]
        read_only_fields = [
            'id', 'file_type', 'file_size', 'file_size_mb', 'status',
            'extracted_text', 'processing_started_at', 'processing_completed_at',
            'processing_error', 'created_at', 'updated_at'
        ]
    
    def get_processing_job(self, obj):
        """Get processing job information"""
        try:
            job = obj.processing_job
            return {
                'id': str(job.id),
                'status': job.status,
                'progress': job.progress,
                'started_at': job.started_at,
                'completed_at': job.completed_at,
                'error_message': job.error_message,
                'text_extraction_completed': job.text_extraction_completed,
                'ai_analysis_completed': job.ai_analysis_completed,
            }
        except ProcessingJob.DoesNotExist:
            return None
    
    def get_analysis_results(self, obj):
        """Get analysis results summary"""
        try:
            analysis = obj.analysis
            return {
                'id': str(analysis.id),
                'completion_percentage': analysis.completion_percentage,
                'is_complete': analysis.is_complete,
                'summary_completed': analysis.summary_completed,
                'key_points_completed': analysis.key_points_completed,
                'sentiment_completed': analysis.sentiment_completed,
                'topics_completed': analysis.topics_completed,
                'created_at': analysis.created_at,
                'updated_at': analysis.updated_at,
            }
        except DocumentAnalysis.DoesNotExist:
            return None
    
    def validate_file(self, value):
        """Validate uploaded file"""
        if not value:
            raise serializers.ValidationError("No file provided")
        
        # Check file size
        if value.size > 10 * 1024 * 1024:  # 10MB
            raise serializers.ValidationError("File size cannot exceed 10MB")
        
        # Check file extension
        allowed_extensions = ['pdf', 'txt', 'docx']
        file_extension = value.name.split('.')[-1].lower()
        
        if file_extension not in allowed_extensions:
            raise serializers.ValidationError(
                f"File type '{file_extension}' not supported. "
                f"Allowed types: {', '.join(allowed_extensions)}"
            )
        
        return value
    
    def create(self, validated_data):
        """Create document with current user"""
        validated_data['user'] = self.context['request'].user
        
        # Set title from filename if not provided
        if not validated_data.get('title'):
            filename = validated_data['file'].name
            validated_data['title'] = filename.rsplit('.', 1)[0]
        
        return super().create(validated_data)


class DocumentListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for document lists"""
    
    file_size_mb = serializers.ReadOnlyField()
    processing_status = serializers.SerializerMethodField()
    
    class Meta:
        model = Document
        fields = [
            'id', 'title', 'file_type', 'file_size', 'file_size_mb',
            'status', 'created_at', 'updated_at', 'processing_status'
        ]
    
    def get_processing_status(self, obj):
        """Get basic processing status"""
        try:
            job = obj.processing_job
            return {
                'status': job.status,
                'progress': job.progress,
            }
        except ProcessingJob.DoesNotExist:
            return None


class DocumentAnalysisSerializer(serializers.ModelSerializer):
    """Serializer for DocumentAnalysis model"""
    
    completion_percentage = serializers.ReadOnlyField()
    is_complete = serializers.ReadOnlyField()
    
    class Meta:
        model = DocumentAnalysis
        fields = [
            'id', 'summary', 'key_points', 'sentiment', 'sentiment_score', 
            'topics', 'model_used', 'total_tokens_used', 'total_processing_time',
            'summary_completed', 'key_points_completed', 'sentiment_completed', 
            'topics_completed', 'completion_percentage', 'is_complete',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ProcessingJobSerializer(serializers.ModelSerializer):
    """Serializer for ProcessingJob model"""
    
    document_title = serializers.CharField(source='document.title', read_only=True)
    logs = serializers.SerializerMethodField()
    
    class Meta:
        model = ProcessingJob
        fields = [
            'id', 'document_title', 'status', 'progress', 'started_at',
            'completed_at', 'error_message', 'retry_count',
            'text_extraction_completed', 'ai_analysis_completed',
            'created_at', 'logs'
        ]
        read_only_fields = ['id', 'created_at']
    
    def get_logs(self, obj):
        """Get recent processing logs"""
        logs = obj.logs.order_by('-created_at')[:10]
        return [
            {
                'id': str(log.id),
                'level': log.level,
                'message': log.message,
                'step': log.step,
                'created_at': log.created_at,
            }
            for log in logs
        ]


class ProcessingLogSerializer(serializers.ModelSerializer):
    """Serializer for ProcessingLog model"""
    
    document_title = serializers.CharField(source='document.title', read_only=True)
    
    class Meta:
        model = ProcessingLog
        fields = [
            'id', 'document_title', 'level', 'message', 'step',
            'metadata', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class DocumentTagSerializer(serializers.ModelSerializer):
    """Serializer for DocumentTag model"""
    
    document_count = serializers.SerializerMethodField()
    
    class Meta:
        model = DocumentTag
        fields = ['id', 'name', 'color', 'description', 'created_at', 'document_count']
        read_only_fields = ['id', 'created_at']
    
    def get_document_count(self, obj):
        """Get count of documents with this tag"""
        return obj.documenttagging_set.count()


class DocumentUploadSerializer(serializers.Serializer):
    """Serializer for document upload with processing options"""
    
    file = serializers.FileField()
    title = serializers.CharField(max_length=255, required=False)
    start_processing = serializers.BooleanField(default=True)
    analysis_types = serializers.ListField(
        child=serializers.ChoiceField(choices=[
            'summary', 'key_points', 'sentiment', 'topics', 'entities'
        ]),
        required=False,
        default=['summary', 'key_points', 'sentiment', 'topics']
    )
    
    def validate_file(self, value):
        """Validate uploaded file"""
        if not value:
            raise serializers.ValidationError("No file provided")
        
        # Check file size
        if value.size > 10 * 1024 * 1024:  # 10MB
            raise serializers.ValidationError("File size cannot exceed 10MB")
        
        # Check file extension
        allowed_extensions = ['pdf', 'txt', 'docx']
        file_extension = value.name.split('.')[-1].lower()
        
        if file_extension not in allowed_extensions:
            raise serializers.ValidationError(
                f"File type '{file_extension}' not supported. "
                f"Allowed types: {', '.join(allowed_extensions)}"
            )
        
        return value
    
    def create(self, validated_data):
        """Create document and optionally start processing"""
        from .tasks import process_document
        
        # Extract processing options
        start_processing = validated_data.pop('start_processing', True)
        analysis_types = validated_data.pop('analysis_types', [])
        
        # Set title from filename if not provided
        if not validated_data.get('title'):
            filename = validated_data['file'].name
            validated_data['title'] = filename.rsplit('.', 1)[0]
        
        # Create document
        validated_data['user'] = self.context['request'].user
        document = Document.objects.create(**validated_data)
        
        # Start processing if requested
        if start_processing:
            print("hi guys precessing started")
            process_document.delay(str(document.id))
        
        return document


class DocumentStatsSerializer(serializers.Serializer):
    """Serializer for document statistics"""
    
    total_documents = serializers.IntegerField()
    processing_documents = serializers.IntegerField()
    completed_documents = serializers.IntegerField()
    failed_documents = serializers.IntegerField()
    total_file_size = serializers.IntegerField()
    avg_processing_time = serializers.FloatField()
    recent_uploads = serializers.IntegerField()
