# /news-article

Purpose: Fetch and normalize article content from a URL.

Request (JSON):

```json
{
  "url": "https://example.com/news/article"
}
```

Response:

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

- `400 Bad Request` invalid URL
- `404 Not Found` article not found
- `502 Bad Gateway` fetch failure

Example request:

```bash
curl -X POST http://localhost:8000/news-article \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/news/article"}'
```
