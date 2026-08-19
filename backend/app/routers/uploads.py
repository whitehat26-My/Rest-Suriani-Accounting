"""Receipt photo upload and retrieval."""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Attachment
from ..schemas import AttachmentOut
from ..serializers import attachment_out

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf"}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB is plenty for a phone photo of a receipt.


@router.post("", response_model=AttachmentOut, status_code=201)
async def upload_receipt(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> AttachmentOut:
    """Store a receipt photo and return its id.

    The id is then passed to the transaction endpoints, so a photo can be taken
    before the amount is known - which is how it actually happens at the till.
    """
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {file.content_type!r}. "
            "Please upload a photo or a PDF.",
        )

    contents = await file.read()
    if len(contents) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="File is larger than 10 MB.")
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    # A random name avoids collisions and stops a caller-supplied name from
    # escaping the upload directory.
    suffix = Path(file.filename or "").suffix[:10]
    stored_name = f"{secrets.token_hex(16)}{suffix}"
    stored_path = settings.upload_dir / stored_name
    stored_path.write_bytes(contents)

    attachment = Attachment(
        filename=Path(file.filename or stored_name).name,
        stored_path=str(stored_path),
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(contents),
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment_out(attachment)


@router.get("/{attachment_id}/file")
def get_file(attachment_id: int, db: Session = Depends(get_db)) -> FileResponse:
    attachment = db.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    path = Path(attachment.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file is missing")
    return FileResponse(path, media_type=attachment.content_type, filename=attachment.filename)
