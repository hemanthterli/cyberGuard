# /image

Purpose: Extract text from images via OCR from text, URL, or base64-encoded file input.
If `API_KEY` is set in the environment, include `X-API-Key` in request headers.

Request schema:

```json
{
  "text": "optional text input",
  "url": "https://example.com/image.png",
  "file_base64": "BASE64_ENCODED_IMAGE",
  "filename": "image.png",
  "mime_type": "image/png"
}
```

Only one of `text`, `url`, or `file_base64` is allowed.

Response schema:

```json
{
  "success": true,
  "message": "Image processed successfully",
  "data": {
    "text": "Extracted text"
  },
  "meta": {
    "request_id": "uuid",
    "source": "image",
    "input_type": "url",
    "duration_ms": 123,
    "size_bytes": 12345,
    "source_url": "https://example.com/image.png"
  },
  "error": null
}
```

Error cases:

- `400 Bad Request` invalid input
- `401 Unauthorized` missing/invalid API key
- `422 Validation Error` OCR failed or empty result
- `500 Internal Server Error` OCR service error

Example request:

```bash
curl -X POST http://localhost:8000/image \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/image.png"}'
```
