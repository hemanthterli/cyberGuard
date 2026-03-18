# /youtube

Purpose: Retrieve YouTube captions from a video URL, ID text, or base64 text file input.
If `API_KEY` is set in the environment, include `X-API-Key` in request headers.

Request schema:

```json
{
  "text": "wGBbCAbLjus",
  "url": "https://www.youtube.com/watch?v=wGBbCAbLjus",
  "file_base64": "BASE64_ENCODED_TEXT",
  "filename": "video_id.txt",
  "mime_type": "text/plain"
}
```

Only one of `text`, `url`, or `file_base64` is allowed.

Response schema:

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

- `400 Bad Request` invalid input
- `401 Unauthorized` missing/invalid API key
- `404 Not Found` captions unavailable
- `502 Bad Gateway` YouTube processing failure

Example request:

```bash
curl -X POST http://localhost:8000/youtube \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.youtube.com/watch?v=wGBbCAbLjus"}'
```
