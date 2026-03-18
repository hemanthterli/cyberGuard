# /text

Purpose: Normalize plain text input.

Request (JSON):

```json
{
  "text": "Sample text input"
}
```

Response:

```json
{
  "success": true,
  "message": "Text processed successfully",
  "data": {
    "text": "Normalized text"
  },
  "meta": {
    "request_id": "uuid",
    "source": "text",
    "input_type": "text",
    "duration_ms": 123,
    "size_bytes": 123,
    "source_url": null
  },
  "error": null
}
```

Error cases:

- `400 Bad Request` empty text
- `422 Validation Error` invalid payload

Example request:

```bash
curl -X POST http://localhost:8000/text \
  -H "Content-Type: application/json" \
  -d '{"text":"hello"}'
```
