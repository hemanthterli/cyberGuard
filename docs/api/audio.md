# /audio

Purpose: Transcribe audio content from text, URL, or base64-encoded file input.
If `API_KEY` is set in the environment, include `X-API-Key` in request headers.

Request schema:

```json
{
  "text": "optional text input",
  "url": "https://example.com/audio.mp3",
  "file_base64": "BASE64_ENCODED_AUDIO",
  "filename": "audio.mp3",
  "mime_type": "audio/mpeg"
}
```

Only one of `text`, `url`, or `file_base64` is allowed.

Response schema:

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

- `400 Bad Request` invalid input
- `401 Unauthorized` missing/invalid API key
- `422 Validation Error` unsupported payload or empty result
- `500 Internal Server Error` transcription failure

Example request:

```bash
curl -X POST http://localhost:8000/audio \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/audio.mp3"}'
```
