# /youtube

Purpose: Retrieve captions from a YouTube URL.

Request (JSON):

```json
{
  "url": "https://www.youtube.com/watch?v=wGBbCAbLjus"
}
```

Response:

```json
{
  "success": true,
  "message": "Youtube processed successfully",
  "data": {
    "text": "Caption text"
  },
  "meta": {
    "request_id": "uuid",
    "source": "youtube",
    "input_type": "url",
    "duration_ms": 123,
    "size_bytes": null,
    "source_url": "https://www.youtube.com/watch?v=wGBbCAbLjus"
  },
  "error": null
}
```

Error cases:

- `400 Bad Request` invalid YouTube URL
- `404 Not Found` captions unavailable
- `502 Bad Gateway` YouTube processing failure

Example request:

```bash
curl -X POST http://localhost:8000/youtube \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.youtube.com/watch?v=wGBbCAbLjus"}'
```
