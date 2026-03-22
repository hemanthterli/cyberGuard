# Generate Complaint

## Endpoint

POST `/generate-complaint`

## Purpose

Draft a formal cyber crime complaint letter from the structured output of the Cyber Laws endpoint.

## Input

```json
{
  "summary": "string",
  "detected_phrases": ["string"],
  "applicable_laws": [
    {
      "law": "string",
      "description": "string"
    }
  ],
  "recommended_actions": ["string"]
}
```

## Output

Plain text complaint letter only (no JSON).

## Notes

- Uses an LLM to draft the complaint letter.
- The response body is `text/plain`.
- Errors are returned as the standard JSON error response.
