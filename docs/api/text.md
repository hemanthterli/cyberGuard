# /text

Purpose: Normalize text input from text, URL, or base64-encoded file input.
If `API_KEY` is set in the environment, include `X-API-Key` in request headers.

Request schema:

```json
{
  "text": "Sample text input",
  "url": "https://example.com/notes",
  "file_base64": "BASE64_ENCODED_TEXT",
  "filename": "notes.txt",
  "mime_type": "text/plain"
}
```

Only one of `text`, `url`, or `file_base64` is allowed.

Response schema:

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

- `400 Bad Request` invalid input
- `401 Unauthorized` missing/invalid API key
- `422 Validation Error` empty payload
- `502 Bad Gateway` fetch failure

Example request:

```bash
curl -X POST http://localhost:8000/text \
  -H "Content-Type: application/json" \
  -d '{"text":"hello"}'
```
