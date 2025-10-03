import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Sum, Avg, Q
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.contrib import messages

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated

from .models import Document, ProcessingJob, DocumentAnalysis, DocumentTag, ProcessingLog
from .serializers import (
    DocumentSerializer, DocumentListSerializer, DocumentAnalysisSerializer,
    ProcessingJobSerializer, DocumentTagSerializer, DocumentUploadSerializer,
    DocumentStatsSerializer, ProcessingLogSerializer
)
from .tasks import process_document

logger = logging.getLogger(__name__)


class DocumentViewSet(viewsets.ModelViewSet):
    """ViewSet for Document CRUD operations"""
    
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_serializer_class(self):
        if self.action == 'list':
            return DocumentListSerializer
        elif self.action == 'upload':
            return DocumentUploadSerializer
        return DocumentSerializer
    
    def get_queryset(self):
        """Filter documents by current user"""
        queryset = Document.objects.filter(user=self.request.user)
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter by file type
        file_type = self.request.query_params.get('file_type')
        if file_type:
            queryset = queryset.filter(file_type=file_type)
        
        # Search by title
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(title__icontains=search)
        
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        """Create document with current user"""
        document = serializer.save(user=self.request.user)
        
        # Start processing automatically
        process_document.delay(str(document.id))
        
        logger.info(f"Document {document.id} created and processing started by user {self.request.user.id}")
    
    @action(detail=False, methods=['post'])
    def upload(self, request):
        """Upload document with processing options"""
        serializer = DocumentUploadSerializer(data=request.data, context={'request': request})
        
        if serializer.is_valid():
            document = serializer.save()
            
            # Return document data
            document_serializer = DocumentSerializer(document, context={'request': request})
            
            return Response({
                'message': 'Document uploaded successfully',
                'document': document_serializer.data
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def reprocess(self, request, pk=None):
        """Restart processing for a document"""
        document = self.get_object()
        
        if document.status == 'processing':
            return Response({
                'error': 'Document is already being processed'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Reset document status
        document.status = 'uploaded'
        document.processing_error = None
        document.extracted_text = None
        document.save()
        
        # Clear existing analysis results
        try:
            document.analysis.delete()
        except DocumentAnalysis.DoesNotExist:
            pass
        
        # Start processing
        process_document.delay(str(document.id))
        
        logger.info(f"Document {document.id} reprocessing started by user {request.user.id}")
        
        return Response({
            'message': 'Document reprocessing started'
        }, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['post'])
    def cancel_processing(self, request, pk=None):
        """Cancel document processing"""
        document = self.get_object()
        
        try:
            processing_job = document.processing_job
            
            if processing_job.status not in ['pending', 'started', 'progress']:
                return Response({
                    'error': 'Cannot cancel processing - job is not active'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Cancel Celery task
            from celery import current_app
            current_app.control.revoke(processing_job.celery_task_id, terminate=True)
            
            # Update status
            processing_job.status = 'revoked'
            processing_job.save()
            
            document.status = 'failed'
            document.processing_error = 'Processing cancelled by user'
            document.save()
            
            logger.info(f"Document {document.id} processing cancelled by user {request.user.id}")
            
            return Response({
                'message': 'Processing cancelled successfully'
            }, status=status.HTTP_200_OK)
            
        except ProcessingJob.DoesNotExist:
            return Response({
                'error': 'No active processing job found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error cancelling processing for document {document.id}: {e}")
            return Response({
                'error': 'Failed to cancel processing'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['get'])
    def analysis(self, request, pk=None):
        """Get detailed analysis results for a document"""
        document = self.get_object()
        
        try:
            analysis = document.analysis
            serializer = DocumentAnalysisSerializer(analysis)
            
            return Response({
                'document_id': str(document.id),
                'document_title': document.title,
                'analysis': serializer.data
            })
        except DocumentAnalysis.DoesNotExist:
            return Response({
                'document_id': str(document.id),
                'document_title': document.title,
                'analysis': None,
                'message': 'No analysis available for this document'
            })
    
    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """Get processing logs for a document"""
        document = self.get_object()
        
        logs = document.processing_logs.order_by('-created_at')
        
        # Pagination
        page_size = int(request.query_params.get('page_size', 20))
        paginator = Paginator(logs, page_size)
        page_number = request.query_params.get('page', 1)
        page_obj = paginator.get_page(page_number)
        
        serializer = ProcessingLogSerializer(page_obj, many=True)
        
        return Response({
            'document_id': str(document.id),
            'logs': serializer.data,
            'pagination': {
                'page': page_obj.number,
                'pages': paginator.num_pages,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
                'total': paginator.count
            }
        })
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get document statistics for current user"""
        user_documents = Document.objects.filter(user=request.user)
        
        # Basic counts
        total_documents = user_documents.count()
        processing_documents = user_documents.filter(status='processing').count()
        completed_documents = user_documents.filter(status='completed').count()
        failed_documents = user_documents.filter(status='failed').count()
        
        # File size statistics
        total_file_size = user_documents.aggregate(
            total_size=Sum('file_size')
        )['total_size'] or 0
        
        # Processing time statistics
        completed_jobs = ProcessingJob.objects.filter(
            document__user=request.user,
            status='success',
            completed_at__isnull=False,
            started_at__isnull=False
        )
        
        avg_processing_time = 0
        if completed_jobs.exists():
            # Calculate average processing time in seconds
            processing_times = []
            for job in completed_jobs:
                if job.completed_at and job.started_at:
                    delta = job.completed_at - job.started_at
                    processing_times.append(delta.total_seconds())
            
            if processing_times:
                avg_processing_time = sum(processing_times) / len(processing_times)
        
        # Recent uploads (last 7 days)
        week_ago = timezone.now() - timedelta(days=7)
        recent_uploads = user_documents.filter(created_at__gte=week_ago).count()
        
        stats_data = {
            'total_documents': total_documents,
            'processing_documents': processing_documents,
            'completed_documents': completed_documents,
            'failed_documents': failed_documents,
            'total_file_size': total_file_size,
            'avg_processing_time': avg_processing_time,
            'recent_uploads': recent_uploads,
        }
        
        serializer = DocumentStatsSerializer(stats_data)
        return Response(serializer.data)


class ProcessingJobViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for ProcessingJob read operations"""
    
    serializer_class = ProcessingJobSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter processing jobs by user's documents"""
        return ProcessingJob.objects.filter(
            document__user=self.request.user
        ).order_by('-created_at')


# Web Interface Views (HTML Templates)

@login_required
def dashboard(request):
    """Main dashboard view"""
    user_documents = Document.objects.filter(user=request.user)
    
    # Get recent documents
    recent_documents = user_documents.order_by('-created_at')[:5]
    
    # Get statistics
    stats = {
        'total_documents': user_documents.count(),
        'processing_documents': user_documents.filter(status='processing').count(),
        'completed_documents': user_documents.filter(status='completed').count(),
        'failed_documents': user_documents.filter(status='failed').count(),
    }
    
    context = {
        'recent_documents': recent_documents,
        'stats': stats,
    }
    
    return render(request, 'documents/dashboard.html', context)


@login_required
def document_list(request):
    """Document list view with filtering and pagination"""
    documents = Document.objects.filter(user=request.user)
    
    # Apply filters
    status_filter = request.GET.get('status')
    if status_filter:
        documents = documents.filter(status=status_filter)
    
    file_type_filter = request.GET.get('file_type')
    if file_type_filter:
        documents = documents.filter(file_type=file_type_filter)
    
    search_query = request.GET.get('search')
    if search_query:
        documents = documents.filter(title__icontains=search_query)
    
    documents = documents.order_by('-created_at')
    
    # Pagination
    paginator = Paginator(documents, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'file_type_filter': file_type_filter,
        'search_query': search_query,
    }
    
    return render(request, 'documents/document_list.html', context)


@login_required
def document_detail(request, document_id):
    """Document detail view"""
    document = get_object_or_404(Document, id=document_id, user=request.user)
    
    # Get analysis results
    try:
        analysis = document.analysis
    except DocumentAnalysis.DoesNotExist:
        analysis = None
    
    # Get processing logs
    processing_logs = document.processing_logs.order_by('-created_at')[:20]
    
    context = {
        'document': document,
        'analysis': analysis,
        'processing_logs': processing_logs,
    }
    
    return render(request, 'documents/document_detail.html', context)


@login_required
def upload_document(request):
    """Document upload view"""
    if request.method == 'POST':
        # Handle file upload
        uploaded_file = request.FILES.get('file')
        title = request.POST.get('title', '')
        
        if uploaded_file:
            # Create document
            if not title:
                title = uploaded_file.name.rsplit('.', 1)[0]
            
            document = Document.objects.create(
                user=request.user,
                title=title,
                file=uploaded_file
            )
            
            # Start processing
            process_document.delay(str(document.id))
            
            messages.success(request, f'Document "{title}" uploaded successfully and processing started.')
            return redirect('documents:document_detail', document_id=document.id)
        else:
            messages.error(request, 'Please select a file to upload.')
    
    return render(request, 'documents/upload.html')


# API Helper Views

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def document_status(request, document_id):
    """Get current document processing status"""
    try:
        document = Document.objects.get(id=document_id, user=request.user)
        
        status_data = {
            'document_id': str(document.id),
            'status': document.status,
            'title': document.title,
            'created_at': document.created_at,
        }
        
        # Add processing job info if exists
        try:
            job = document.processing_job
            status_data.update({
                'job_status': job.status,
                'progress': job.progress,
                'started_at': job.started_at,
                'completed_at': job.completed_at,
                'error_message': job.error_message,
            })
        except ProcessingJob.DoesNotExist:
            pass
        
        return Response(status_data)
        
    except Document.DoesNotExist:
        return Response({
            'error': 'Document not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def health_check(request):
    """Health check endpoint"""
    return Response({
        'status': 'healthy',
        'timestamp': timezone.now(),
        'user': request.user.username
    })


#process_document.delay("036b6afa-bb02-4b03-be3a-98234e01938a")
