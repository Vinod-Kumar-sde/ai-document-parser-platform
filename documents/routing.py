from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/documents/(?P<document_id>[0-9a-f-]+)/$', consumers.DocumentProcessingConsumer.as_asgi()),
    re_path(r'ws/documents/$', consumers.DocumentListConsumer.as_asgi()),
]
