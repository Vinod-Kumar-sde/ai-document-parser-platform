# AI Document Processor

A Django application demonstrating production-ready background processing with Celery, real-time updates with Django Channels, and AI-powered document analysis using Google Gemini.

## Features

- Async document processing with Celery
- Real-time progress updates via WebSockets
- AI-powered analysis (summarization, sentiment, key points, topics)
- Support for PDF, TXT, and DOCX files
- RESTful API with Django REST Framework
- Progress tracking and error handling

## Architecture

```
Client → Django View → Celery Queue → Worker → Redis → Client (WebSocket)
```

**Flow:**
1. User uploads document via Django API
2. Task queued in Redis via Celery
3. Worker processes document (text extraction + AI analysis)
4. Real-time updates sent via WebSocket
5. Results stored in database

## Prerequisites

- Python 3.11+
- Redis (for Celery broker and Django Channels)
- Google Gemini API key

## Quick Start

### 1. Environment Setup

```bash
# Clone and navigate to directory
cd ai-doc-prossessor-red

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
```

### 2. Configure Environment Variables

Edit `.env` file:

```env
# Required
GEMINI_API_KEY=your_gemini_api_key_here

# Optional
SECRET_KEY=your-secret-key
DEBUG=True
DATABASE_URL=sqlite:///db.sqlite3
REDIS_URL=redis://localhost:6379/0
```

Get Gemini API key: [Google AI Studio](https://makersuite.google.com/app/apikey)

### 3. Database Setup

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 4. Start Services

**Terminal 1 - Redis:**
```bash
redis-server
```

**Terminal 2 - Celery Worker:**
```bash
celery -A core worker --loglevel=info
```

**Terminal 3 - Celery Beat (periodic tasks):**
```bash
celery -A core beat --loglevel=info
```

**Terminal 4 - Django Server:**
```bash
# For WebSocket support (recommended)
daphne -b 0.0.0.0 -p 8000 core.asgi:application

# OR for development without WebSocket
python manage.py runserver
```

### 5. Access Application

- Web Interface: http://localhost:8000
- Admin Panel: http://localhost:8000/admin

## API Endpoints

### Documents
- `POST /api/documents/upload/` - Upload document
- `GET /api/documents/` - List documents
- `GET /api/documents/{id}/` - Get document details
- `POST /api/documents/{id}/reprocess/` - Restart processing
- `POST /api/documents/{id}/cancel_processing/` - Cancel processing
- `GET /api/documents/{id}/analysis/` - Get AI analysis results
- `GET /api/documents/{id}/logs/` - Get processing logs

### WebSocket
```javascript
// Connect to document updates
const socket = new WebSocket('ws://localhost:8000/ws/documents/{document_id}/');

socket.onmessage = (e) => {
    const data = JSON.parse(e.data);
    console.log('Progress:', data.progress, data.message);
};
```

## Project Structure

```
ai-doc-prossessor-red/
├── core/
│   ├── celery.py      # Celery configuration
│   ├── settings.py    # Django settings
│   └── asgi.py        # ASGI configuration
├── documents/
│   ├── models.py      # Document, ProcessingJob, Analysis models
│   ├── tasks.py       # Celery tasks
│   ├── views.py       # API views
│   ├── consumers.py   # WebSocket consumers
│   └── serializers.py # DRF serializers
└── templates/         # HTML templates
```

## Key Components

### Celery Task Processing
```python
@shared_task(bind=True, max_retries=3)
def process_document(self, document_id):
    # Extract text
    # Run AI analysis
    # Send WebSocket updates
    # Handle retries
```

### WebSocket Updates
```python
def send_websocket_update(document_id, event_type, data):
    channel_layer.group_send(f'document_{document_id}', {...})
```

### AI Analysis
- Summarization
- Key points extraction
- Sentiment analysis
- Topic identification

## Monitoring

### Celery Tasks
```bash
# View active tasks
celery -A core inspect active

# View registered tasks
celery -A core inspect registered

# View stats
celery -A core inspect stats
```

### Optional: Flower UI
```bash
pip install flower
celery -A core flower --port=5555
# Access at http://localhost:5555
```

## Configuration

### Celery Settings
- Rate limiting: 10 tasks/minute
- Time limit: 30 minutes per task
- Retry: 3 attempts with exponential backoff
- Periodic cleanup tasks

### File Upload
- Max size: 10MB (configurable)
- Supported types: PDF, TXT, DOCX
- Storage: Media directory

## Troubleshooting

**Redis Connection Error:**
```bash
redis-cli ping  # Should return PONG
```

**Celery Not Processing:**
```bash
celery -A core inspect active  # Check if worker is running
```

**WebSocket Connection Failed:**
- Ensure using Daphne (not runserver)
- Check Redis is running
- Verify CHANNEL_LAYERS in settings

**Gemini API Errors:**
- Verify API key is set in .env
- Check API quotas at Google AI Studio
- Review rate limiting settings

## Testing

```bash
# Run all tests
python manage.py test

# Run with coverage
coverage run --source='.' manage.py test
coverage report
```

## Development

### Code Structure
- Models: Database schema with UUIDs
- Tasks: Celery async processing
- Consumers: WebSocket handlers
- Views: REST API endpoints
- Serializers: Data validation

### Best Practices
- Use UUIDs for primary keys
- Implement retry logic with exponential backoff
- Log all processing steps
- Send real-time updates via WebSocket
- Handle errors gracefully

## License

MIT License

## Support

For issues and questions, please create an issue on the repository.
