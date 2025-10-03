import os
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from celery import shared_task, current_task
from celery.exceptions import Retry
from django.conf import settings
from django.utils import timezone
from django.core.files.base import ContentFile
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

import google.generativeai as genai
import PyPDF2
import pdfplumber
from docx import Document as DocxDocument

from .models import Document, ProcessingJob, DocumentAnalysis, ProcessingLog

logger = logging.getLogger(__name__)

# Configure Gemini AI
genai.configure(api_key=settings.GEMINI_API_KEY)


def send_websocket_update(document_id: str, event_type: str, data: Dict[str, Any]):
    """Send WebSocket update to connected clients"""
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'document_{document_id}',
                {
                    'type': event_type,
                    'document_id': document_id,
                    'timestamp': timezone.now().isoformat(),
                    **data
                }
            )
    except Exception as e:
        logger.error(f"Error sending WebSocket update: {e}")


def log_processing_step(document_id: str, processing_job_id: str, level: str, 
                       message: str, step: str = '', metadata: Dict = None):
    """Log processing step to database and WebSocket"""
    try:
        ProcessingLog.objects.create(
            document_id=document_id,
            processing_job_id=processing_job_id,
            level=level,
            message=message,
            step=step,
            metadata=metadata or {}
        )
        
        # Send WebSocket update
        send_websocket_update(document_id, 'processing_update', {
            'status': 'processing',
            'progress': current_task.request.get('progress', 0),
            'message': message,
            'step': step
        })
        
    except Exception as e:
        logger.error(f"Error logging processing step: {e}")


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_document(self, document_id: str) -> Dict[str, Any]:
    """Main task to process a document through the complete pipeline"""
    try:
        # Get document and create/update processing job
        document = Document.objects.get(id=document_id)
        processing_job, created = ProcessingJob.objects.get_or_create(
            document=document,
            defaults={
                'celery_task_id': self.request.id,
                'status': 'started',
                'started_at': timezone.now()
            }
        )
        
        if not created:
            processing_job.celery_task_id = self.request.id
            processing_job.status = 'started'
            processing_job.started_at = timezone.now()
            processing_job.save()
        
        # Update document status
        document.status = 'processing'
        document.processing_started_at = timezone.now()
        document.save()
        
        log_processing_step(
            document_id, str(processing_job.id), 'info',
            f'Starting document processing for {document.title}',
            'initialization'
        )
        
        # Step 1: Extract text from document
        self.update_state(state='PROGRESS', meta={'progress': 20, 'step': 'text_extraction'})
        processing_job.progress = 20
        processing_job.save()
        
        extracted_text = extract_text_from_document(document)
        
        if not extracted_text:
            raise Exception("Failed to extract text from document")
        
        # Save extracted text
        document.extracted_text = extracted_text
        document.save()
        
        processing_job.text_extraction_completed = True
        processing_job.progress = 50
        processing_job.save()
        
        log_processing_step(
            document_id, str(processing_job.id), 'info',
            f'Text extraction completed. Extracted {len(extracted_text)} characters.',
            'text_extraction'
        )
        
        # Step 2: Analyze with Gemini AI
        self.update_state(state='PROGRESS', meta={'progress': 50, 'step': 'ai_analysis'})
        
        analysis_results = analyze_document_with_gemini(document, extracted_text)
        
        processing_job.ai_analysis_completed = True
        processing_job.progress = 90
        processing_job.save()
        
        log_processing_step(
            document_id, str(processing_job.id), 'info',
            f'AI analysis completed. Generated {len(analysis_results)} analysis results.',
            'ai_analysis'
        )
        
        # Step 3: Finalize processing
        self.update_state(state='PROGRESS', meta={'progress': 100, 'step': 'finalization'})
        
        document.status = 'completed'
        document.processing_completed_at = timezone.now()
        document.save()
        
        processing_job.status = 'success'
        processing_job.progress = 100
        processing_job.completed_at = timezone.now()
        processing_job.save()
        
        log_processing_step(
            document_id, str(processing_job.id), 'info',
            'Document processing completed successfully',
            'finalization'
        )
        
        # Send completion notification
        send_websocket_update(document_id, 'processing_complete', {
            'status': 'completed',
            'results': {
                'text_length': len(extracted_text),
                'analysis_count': len(analysis_results)
            }
        })
        
        return {
            'status': 'success',
            'document_id': document_id,
            'text_length': len(extracted_text),
            'analysis_results': len(analysis_results)
        }
        
    except Exception as exc:
        logger.error(f"Error processing document {document_id}: {exc}")
        
        # Update document and job status
        try:
            document = Document.objects.get(id=document_id)
            document.status = 'failed'
            document.processing_error = str(exc)
            document.save()
            
            processing_job = ProcessingJob.objects.get(document=document)
            processing_job.status = 'failure'
            processing_job.error_message = str(exc)
            processing_job.save()
            
            log_processing_step(
                document_id, str(processing_job.id), 'error',
                f'Processing failed: {str(exc)}',
                'error'
            )
            
            # Send error notification
            send_websocket_update(document_id, 'processing_error', {
                'error': str(exc)
            })
            
        except Exception as e:
            logger.error(f"Error updating failed document status: {e}")
        
        # Retry logic
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying document processing for {document_id} (attempt {self.request.retries + 1})")
            raise self.retry(countdown=60 * (2 ** self.request.retries))
        
        raise exc


def extract_text_from_document(document: Document) -> str:
    """Extract text from different document types"""
    
    file_path = document.file.path
    file_type = document.file_type.lower()
    
    try:
        if file_type == 'pdf':
            return extract_text_from_pdf(file_path)
        elif file_type == 'txt':
            return extract_text_from_txt(file_path)
        elif file_type == 'docx':
            return extract_text_from_docx(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")
            
    except Exception as e:
        logger.error(f"Error extracting text from {file_type} file: {e}")
        raise


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from PDF file using pdfplumber (more reliable than PyPDF2)"""
    
    text_content = []
    
    try:
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                try:
                    page_text = page.extract_text()
                    if page_text:
                        text_content.append(f"--- Page {page_num} ---\n{page_text}\n")
                except Exception as e:
                    logger.warning(f"Error extracting text from page {page_num}: {e}")
                    continue
        
        if not text_content:
            # Fallback to PyPDF2 if pdfplumber fails
            logger.info("Falling back to PyPDF2 for text extraction")
            return extract_text_from_pdf_pypdf2(file_path)
        
        return '\n'.join(text_content)
        
    except Exception as e:
        logger.error(f"Error with pdfplumber extraction: {e}")
        # Fallback to PyPDF2
        return extract_text_from_pdf_pypdf2(file_path)


def extract_text_from_pdf_pypdf2(file_path: str) -> str:
    """Fallback PDF text extraction using PyPDF2"""
    
    text_content = []
    
    with open(file_path, 'rb') as file:
        pdf_reader = PyPDF2.PdfReader(file)
        
        for page_num, page in enumerate(pdf_reader.pages, 1):
            try:
                page_text = page.extract_text()
                if page_text:
                    text_content.append(f"--- Page {page_num} ---\n{page_text}\n")
            except Exception as e:
                logger.warning(f"Error extracting text from page {page_num} with PyPDF2: {e}")
                continue
    
    return '\n'.join(text_content)


def extract_text_from_txt(file_path: str) -> str:
    """Extract text from TXT file"""
    
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    except UnicodeDecodeError:
        # Try with different encoding
        with open(file_path, 'r', encoding='latin-1') as file:
            return file.read()


def extract_text_from_docx(file_path: str) -> str:
    """Extract text from DOCX file"""
    
    doc = DocxDocument(file_path)
    text_content = []
    
    for paragraph in doc.paragraphs:
        if paragraph.text.strip():
            text_content.append(paragraph.text)
    
    return '\n'.join(text_content)


def analyze_document_with_gemini(document: Document, text_content: str) -> dict:
    """Analyze document using Gemini AI and save to single DocumentAnalysis record"""
    
    model = genai.GenerativeModel(settings.GEMINI_MODEL)
    
    # Get or create the analysis record
    analysis, created = DocumentAnalysis.objects.get_or_create(
        document=document,
        defaults={'model_used': settings.GEMINI_MODEL}
    )
    
    total_processing_time = 0
    total_tokens_used = 0
    
    # Define analysis types and their prompts
    analysis_types = {
        'summary': {
            'prompt': f"""
            Please provide a concise summary of the following document in 2-3 sentences:
            
            {text_content[:4000]}  # Limit text to avoid token limits
            """,
            'description': 'Document Summary',
            'field': 'summary'
        },
        'key_points': {
            'prompt': f"""
            Extract the key points from the following document. Present them as a JSON list of strings:
            
            {text_content[:4000]}
            """,
            'description': 'Key Points Extraction',
            'field': 'key_points'
        },
        'sentiment': {
            'prompt': f"""
            Analyze the sentiment of the following document. Respond with only one word: positive, negative, or neutral:
            
            {text_content[:4000]}
            """,
            'description': 'Sentiment Analysis',
            'field': 'sentiment'
        },
        'topics': {
            'prompt': f"""
            Identify the main topics and themes discussed in the following document. 
            Present them as a JSON list of strings:
            
            {text_content[:4000]}
            """,
            'description': 'Topic Extraction',
            'field': 'topics'
        }
    }
    
    for analysis_type, config in analysis_types.items():
        try:
            logger.info(f"Running {config['description']} for document {document.id}")
            
            start_time = time.time()
            
            response = model.generate_content(
                config['prompt'],
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=settings.GEMINI_MAX_TOKENS,
                    temperature=settings.GEMINI_TEMPERATURE,
                )
            )
            
            processing_time = time.time() - start_time
            total_processing_time += processing_time
            
            if response.text:
                # Get token usage safely
                tokens_used = 0
                try:
                    if hasattr(response, 'usage_metadata') and response.usage_metadata:
                        tokens_used = getattr(response.usage_metadata, 'total_token_count', 0)
                        total_tokens_used += tokens_used
                except Exception:
                    pass
                
                # Process and save the result based on type
                result_text = response.text.strip()
                
                if analysis_type == 'summary':
                    analysis.summary = result_text
                    analysis.summary_completed = True
                    
                elif analysis_type == 'key_points':
                    # Try to parse as JSON, fallback to simple list
                    try:
                        import json
                        key_points = json.loads(result_text)
                        if isinstance(key_points, list):
                            analysis.key_points = key_points
                        else:
                            # If not a list, split by lines
                            analysis.key_points = [line.strip() for line in result_text.split('\n') if line.strip()]
                    except:
                        # Fallback: split by lines or bullet points
                        lines = result_text.replace('•', '').replace('-', '').split('\n')
                        analysis.key_points = [line.strip() for line in lines if line.strip()]
                    analysis.key_points_completed = True
                    
                elif analysis_type == 'sentiment':
                    # Clean and validate sentiment
                    sentiment = result_text.lower().strip()
                    if sentiment in ['positive', 'negative', 'neutral']:
                        analysis.sentiment = sentiment
                        analysis.sentiment_score = 0.8  # Default confidence
                    else:
                        # Try to extract sentiment from longer response
                        if 'positive' in sentiment:
                            analysis.sentiment = 'positive'
                        elif 'negative' in sentiment:
                            analysis.sentiment = 'negative'
                        else:
                            analysis.sentiment = 'neutral'
                        analysis.sentiment_score = 0.6  # Lower confidence
                    analysis.sentiment_completed = True
                    
                elif analysis_type == 'topics':
                    # Try to parse as JSON, fallback to simple list
                    try:
                        import json
                        topics = json.loads(result_text)
                        if isinstance(topics, list):
                            analysis.topics = topics
                        else:
                            # If not a list, split by lines
                            analysis.topics = [line.strip() for line in result_text.split('\n') if line.strip()]
                    except:
                        # Fallback: split by lines or commas
                        if ',' in result_text:
                            analysis.topics = [topic.strip() for topic in result_text.split(',') if topic.strip()]
                        else:
                            lines = result_text.split('\n')
                            analysis.topics = [line.strip() for line in lines if line.strip()]
                    analysis.topics_completed = True
                
                logger.info(f"Completed {config['description']} in {processing_time:.2f}s")
            
            # Small delay between API calls to respect rate limits
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"Error in {config['description']}: {e}")
            # Continue with other analysis types even if one fails
            continue
    
    # Update totals and save
    analysis.total_processing_time = total_processing_time
    analysis.total_tokens_used = total_tokens_used if total_tokens_used > 0 else None
    analysis.save()
    
    return {
        'analysis_id': str(analysis.id),
        'completion_percentage': analysis.completion_percentage,
        'total_processing_time': total_processing_time,
        'total_tokens_used': total_tokens_used
    }


@shared_task
def cleanup_failed_jobs():
    """Cleanup failed processing jobs older than 24 hours"""
    
    cutoff_time = timezone.now() - timedelta(hours=24)
    
    failed_jobs = ProcessingJob.objects.filter(
        status='failure',
        created_at__lt=cutoff_time
    )
    
    count = failed_jobs.count()
    failed_jobs.delete()
    
    logger.info(f"Cleaned up {count} failed processing jobs")
    return f"Cleaned up {count} failed jobs"


@shared_task
def cleanup_old_logs():
    """Cleanup processing logs older than 7 days"""
    
    cutoff_time = timezone.now() - timedelta(days=7)
    
    old_logs = ProcessingLog.objects.filter(
        created_at__lt=cutoff_time
    )
    
    count = old_logs.count()
    old_logs.delete()
    
    logger.info(f"Cleaned up {count} old processing logs")
    return f"Cleaned up {count} old logs"


@shared_task
def retry_failed_documents():
    """Retry processing for documents that failed due to temporary issues"""
    
    # Find documents that failed in the last hour (might be temporary issues)
    recent_failures = Document.objects.filter(
        status='failed',
        processing_started_at__gte=timezone.now() - timedelta(hours=1)
    ).exclude(
        processing_error__icontains='cancelled'
    )
    
    retried_count = 0
    
    for document in recent_failures:
        try:
            # Check if we should retry (not too many retries already)
            processing_job = getattr(document, 'processing_job', None)
            if processing_job and processing_job.retry_count < 3:
                
                # Reset document status
                document.status = 'uploaded'
                document.processing_error = None
                document.save()
                
                # Update processing job
                processing_job.retry_count += 1
                processing_job.status = 'retry'
                processing_job.save()
                
                # Restart processing
                process_document.delay(str(document.id))
                retried_count += 1
                
                logger.info(f"Retrying processing for document {document.id}")
                
        except Exception as e:
            logger.error(f"Error retrying document {document.id}: {e}")
            continue
    
    logger.info(f"Retried processing for {retried_count} documents")
    return f"Retried {retried_count} documents"
