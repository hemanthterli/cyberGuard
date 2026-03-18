# /audio

Purpose: Transcribe audio from an uploaded file.

Request (multipart/form-data):

- `file` (required): audio file

Response:

```json
{
  "success": true,
  "message": "Audio processed successfully",
  "data": {
    "text": "Transcribed text"
  },
  "meta": {
    "request_id": "uuid",
    "source": "audio",
    "input_type": "file",
    "duration_ms": 123,
    "size_bytes": 12345,
    "source_url": null
  },
  "error": null
}
```

Error cases:

- `400 Bad Request` unsupported file type or empty file
- `413 Payload Too Large` file exceeds size limit
- `422 Validation Error` empty transcription
- `500 Internal Server Error` transcription failure

Example request:

```bash
curl -X POST http://localhost:8000/audio \
  -F "file=@/path/to/audio.mp3"
```
