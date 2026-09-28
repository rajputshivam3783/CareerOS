from fastapi import HTTPException, UploadFile

from app.core.hardening import validate_file_signature


async def read_upload_limited(
    file: UploadFile,
    *,
    max_bytes: int,
    allowed_extensions: set[str],
    allowed_content_types: set[str] | None = None,
    verify_signature: bool = True,
) -> bytes:
    """Read an upload with size, extension, content-type and (V25.6) content checks.

    ``verify_signature`` (default True) additionally requires the bytes to look like the
    format the extension claims (PDF/PNG/JPEG/DOC/DOCX/TXT magic bytes, plus zip-bomb and
    path-traversal checks for DOCX) - the extension and the client-supplied Content-Type are
    trivially spoofed. The size check runs first, so an oversized file still returns 413.
    """
    filename = (file.filename or "").lower()
    if not any(filename.endswith(ext) for ext in allowed_extensions):
        raise HTTPException(400, f"Unsupported file type. Allowed: {', '.join(sorted(allowed_extensions))}")
    if allowed_content_types and file.content_type and file.content_type not in allowed_content_types:
        raise HTTPException(400, "Unsupported file content type")
    data = await file.read(max_bytes + 1)
    if not data:
        raise HTTPException(400, "Uploaded file is empty")
    if len(data) > max_bytes:
        raise HTTPException(413, f"File is too large. Maximum size is {max_bytes // (1024 * 1024)} MB")
    if verify_signature:
        try:
            validate_file_signature(filename, data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return data
