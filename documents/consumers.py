import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User
from .models import Document, ProcessingJob, DocumentAnalysis

logger = logging.getLogger(__name__)


class DocumentProcessingConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time document processing updates"""
    
    async def connect(self):
        self.document_id = self.scope['url_route']['kwargs']['document_id']
        self.room_group_name = f'document_{self.document_id}'
        
        # Check if user is authenticated and has access to this document
        if not await self.check_document_access():
            await self.close()
            return
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Send current document status
        await self.send_document_status()
        
        logger.info(f"WebSocket connected for document {self.document_id}")
    
    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        
        logger.info(f"WebSocket disconnected for document {self.document_id}")
    
    async def receive(self, text_data):
        """Handle messages from WebSocket"""
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type')
            
            if message_type == 'get_status':
                await self.send_document_status()
            elif message_type == 'cancel_processing':
                await self.cancel_processing()
            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': f'Unknown message type: {message_type}'
                }))
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Internal server error'
            }))
    
    # Receive message from room group
    async def processing_update(self, event):
        """Send processing update to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'processing_update',
            'document_id': event['document_id'],
            'status': event['status'],
            'progress': event['progress'],
            'message': event.get('message', ''),
            'step': event.get('step', ''),
            'timestamp': event.get('timestamp')
        }))
    
    async def processing_complete(self, event):
        """Send processing completion to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'processing_complete',
            'document_id': event['document_id'],
            'status': event['status'],
            'results': event.get('results', {}),
            'timestamp': event.get('timestamp')
        }))
    
    async def processing_error(self, event):
        """Send processing error to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'processing_error',
            'document_id': event['document_id'],
            'error': event['error'],
            'timestamp': event.get('timestamp')
        }))
    
    @database_sync_to_async
    def check_document_access(self):
        """Check if user has access to this document"""
        try:
            user = self.scope['user']
            if not user.is_authenticated:
                return False
            
            document = Document.objects.get(id=self.document_id, user=user)
            return True
        except Document.DoesNotExist:
            return False
        except Exception as e:
            logger.error(f"Error checking document access: {e}")
            return False
    
    @database_sync_to_async
    def get_document_status(self):
        """Get current document and processing job status"""
        try:
            document = Document.objects.get(id=self.document_id)
            processing_job = getattr(document, 'processing_job', None)
            
            status_data = {
                'document_id': str(document.id),
                'status': document.status,
                'title': document.title,
                'file_type': document.file_type,
                'created_at': document.created_at.isoformat(),
            }
            
            if processing_job:
                status_data.update({
                    'job_status': processing_job.status,
                    'progress': processing_job.progress,
                    'started_at': processing_job.started_at.isoformat() if processing_job.started_at else None,
                    'completed_at': processing_job.completed_at.isoformat() if processing_job.completed_at else None,
                    'text_extraction_completed': processing_job.text_extraction_completed,
                    'ai_analysis_completed': processing_job.ai_analysis_completed,
                })
            
            return status_data
        except Document.DoesNotExist:
            return None
        except Exception as e:
            logger.error(f"Error getting document status: {e}")
            return None
    
    async def send_document_status(self):
        """Send current document status to WebSocket"""
        status_data = await self.get_document_status()
        if status_data:
            await self.send(text_data=json.dumps({
                'type': 'document_status',
                **status_data
            }))
        else:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Document not found'
            }))
    
    @database_sync_to_async
    def cancel_processing_job(self):
        """Cancel the processing job"""
        try:
            document = Document.objects.get(id=self.document_id)
            processing_job = getattr(document, 'processing_job', None)
            
            if processing_job and processing_job.status in ['pending', 'started', 'progress']:
                # Import here to avoid circular imports
                from celery import current_app
                current_app.control.revoke(processing_job.celery_task_id, terminate=True)
                
                processing_job.status = 'revoked'
                processing_job.save()
                
                document.status = 'failed'
                document.processing_error = 'Processing cancelled by user'
                document.save()
                
                return True
            return False
        except Exception as e:
            logger.error(f"Error cancelling processing job: {e}")
            return False
    
    async def cancel_processing(self):
        """Handle processing cancellation request"""
        success = await self.cancel_processing_job()
        if success:
            await self.send(text_data=json.dumps({
                'type': 'processing_cancelled',
                'document_id': self.document_id,
                'message': 'Processing cancelled successfully'
            }))
        else:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Could not cancel processing'
            }))


class DocumentListConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for document list updates"""
    
    async def connect(self):
        # Check if user is authenticated
        if not self.scope['user'].is_authenticated:
            await self.close()
            return
        
        self.user_id = self.scope['user'].id
        self.room_group_name = f'user_documents_{self.user_id}'
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        logger.info(f"Document list WebSocket connected for user {self.user_id}")
    
    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        logger.info(f"Document list WebSocket disconnected for user {self.user_id}")
    
    async def receive(self, text_data):
        """Handle messages from WebSocket"""
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type')
            
            if message_type == 'get_documents':
                await self.send_document_list()
            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': f'Unknown message type: {message_type}'
                }))
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))
    
    # Receive message from room group
    async def document_created(self, event):
        """Send document creation notification"""
        await self.send(text_data=json.dumps({
            'type': 'document_created',
            'document': event['document']
        }))
    
    async def document_updated(self, event):
        """Send document update notification"""
        await self.send(text_data=json.dumps({
            'type': 'document_updated',
            'document': event['document']
        }))
    
    async def document_deleted(self, event):
        """Send document deletion notification"""
        await self.send(text_data=json.dumps({
            'type': 'document_deleted',
            'document_id': event['document_id']
        }))
    
    @database_sync_to_async
    def get_user_documents(self):
        """Get user's documents"""
        try:
            user = User.objects.get(id=self.user_id)
            documents = Document.objects.filter(user=user).order_by('-created_at')[:20]
            
            document_list = []
            for doc in documents:
                doc_data = {
                    'id': str(doc.id),
                    'title': doc.title,
                    'file_type': doc.file_type,
                    'file_size': doc.file_size,
                    'status': doc.status,
                    'created_at': doc.created_at.isoformat(),
                    'updated_at': doc.updated_at.isoformat(),
                }
                
                # Add processing job info if exists
                processing_job = getattr(doc, 'processing_job', None)
                if processing_job:
                    doc_data['processing'] = {
                        'status': processing_job.status,
                        'progress': processing_job.progress,
                    }
                
                document_list.append(doc_data)
            
            return document_list
        except Exception as e:
            logger.error(f"Error getting user documents: {e}")
            return []
    
    async def send_document_list(self):
        """Send document list to WebSocket"""
        documents = await self.get_user_documents()
        await self.send(text_data=json.dumps({
            'type': 'document_list',
            'documents': documents
        }))
