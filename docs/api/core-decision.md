# /core-decision

Purpose: Analyze content for bullying or negative targeting using the CORE decision model.

Request (JSON):

```json
{
  "source": "https://youtube.com/test",
  "source_type": "youtube",
  "content": "I’ve heard from multiple people that you lie constantly...",
  "user_context": "optional background context"
}
```

Response:

```json
{
  "success": true,
  "message": "Core decision processed successfully",
  "data": {
    "bullying": "yes",
    "description": "Short explanation",
    "phrases": "Exact phrases",
    "source": "https://youtube.com/test",
    "impact_action": "Report/complaint/legal action"
  },
  "meta": {
    "request_id": "uuid",
    "source": "core-decision",
    "input_type": "json",
    "duration_ms": 123,
    "size_bytes": null,
    "source_url": null
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
curl -X POST http://localhost:8000/core-decision \
  -H "Content-Type: application/json" \
  -d '{"source":"https://youtube.com/test","source_type":"youtube","content":"...","user_context":"..."}'
```
