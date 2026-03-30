# /get-cyber-laws

Purpose: Generate a structured legal analysis and complaint guidance using content, core decision, and retrieved cyber law snippets.

Request (JSON):

```json
{
  "content": "Original or enhanced content",
  "core_decision": {
    "bullying": "yes",
    "description": "Short explanation",
    "phrases": "Exact phrases",
    "source": "https://example.com",
    "impact_action": "Report",
    "core_cybercrime": "20-25 word cybercrime summary"
  },
  "retrieved_laws": [
    "law snippet 1",
    "law snippet 2"
  ]
}
```

Response:

```json
{
  "success": true,
  "message": "Cyber law analysis generated successfully",
  "data": {
    "summary": "Explanation of the issue",
    "detected_phrases": ["phrase 1", "phrase 2"],
    "applicable_laws": [
      {"law": "Act/Section", "description": "Brief explanation", "source": "https://..."}
    ],
    "recommended_actions": [
      "Step 1...",
      "Step 2..."
    ]
  },
  "meta": {
    "request_id": "uuid",
    "source": "get-cyber-laws",
    "input_type": "json",
    "duration_ms": 123,
    "size_bytes": null,
    "source_url": null
  },
  "error": null
}
```

Error cases:

- `400 Bad Request` invalid inputs
- `422 Validation Error` invalid payload
- `500 Internal Server Error` missing Gemini config/dependency
- `502 Bad Gateway` model failure

Example request:

```bash
curl -X POST http://localhost:8000/get-cyber-laws \
  -H "Content-Type: application/json" \
  -d '{"content":"...","core_decision":{...},"retrieved_laws":["..."]}'
```
