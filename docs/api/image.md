# /image

Purpose: Extract text from an uploaded JPG/PNG image using OCR.

Request (multipart/form-data):

- `file` (required): JPG or PNG image

Response:

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
    "input_type": "file",
    "duration_ms": 123,
    "size_bytes": 12345,
    "source_url": null
  },
  "error": null
}
```

Error cases:

- `400 Bad Request` unsupported file type or empty file
- `413 Payload Too Large` file exceeds size limit
- `422 Validation Error` OCR failed or empty result
- `500 Internal Server Error` OCR service error

Example request:

```bash
curl -X POST http://localhost:8000/image \
  -F "file=@/path/to/image.png"
```
