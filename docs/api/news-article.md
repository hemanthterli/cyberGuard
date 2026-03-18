# /news-article

Purpose: Fetch and normalize news article content from text, URL, or base64-encoded file input.
If `API_KEY` is set in the environment, include `X-API-Key` in request headers.

Request schema:

```json
{
  "text": "optional article text",
  "url": "https://example.com/news/article",
  "file_base64": "BASE64_ENCODED_TEXT",
  "filename": "article.txt",
  "mime_type": "text/plain"
}
```

Only one of `text`, `url`, or `file_base64` is allowed.

Response schema:

```json
{
  "success": true,
  "message": "News Article processed successfully",
  "data": {
    "text": "Markdown article text"
  },
  "meta": {
    "request_id": "uuid",
    "source": "news-article",
    "input_type": "url",
    "duration_ms": 123,
    "size_bytes": 12345,
    "source_url": "https://example.com/news/article"
  },
  "error": null
}
```

Error cases:

- `400 Bad Request` invalid input
- `401 Unauthorized` missing/invalid API key
- `404 Not Found` article not found
- `502 Bad Gateway` fetch failure

Example request:

```bash
curl -X POST http://localhost:8000/news-article \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/news/article"}'
```
