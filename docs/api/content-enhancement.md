# /content-enhancement

Purpose: Clean, refine, and structure noisy content while preserving original meaning.

Request (JSON):

```json
{
  "source_type": "news_article",
  "source": "https://example.com/article",
  "content": "Raw extracted text with noise..."
}
```

Response:

```json
{
  "success": true,
  "message": "Content Enhancement processed successfully",
  "data": {
    "text": "Cleaned and structured content"
  },
  "meta": {
    "request_id": "uuid",
    "source": "content-enhancement",
    "input_type": "json",
    "duration_ms": 123,
    "size_bytes": 456,
    "source_url": "https://example.com/article"
  },
  "error": null
}
```

Error cases:

- `400 Bad Request` empty fields
- `422 Validation Error` invalid payload
- `500 Internal Server Error` missing Gemini config/dependency
- `502 Bad Gateway` model failure

Example request:

```bash
curl -X POST http://localhost:8000/content-enhancement \
  -H "Content-Type: application/json" \
  -d '{"source_type":"news_article","source":"https://example.com/article","content":"..."}'
```
