"""Receipt photo upload and retrieval."""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..dependencies import require_finance, require_user
from ..models import Attachment
from ..schemas import AttachmentOut
from ..serializers import attachment_out

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf"}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB is plenty for a phone photo of a receipt.
CHUNK = 1024 * 1024

# Magic-byte signatures for the types we accept. The multipart Content-Type
# header is attacker-controlled, so the declared type is checked against the
# actual leading bytes and a mismatch is rejected.
_MAGIC = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "application/pdf": (b"%PDF-",),
}


def _looks_like(content_type: str, head: bytes) -> bool:
    """Whether the leading bytes are consistent with the declared type."""
    if content_type == "image/webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if content_type == "image/heic":
        return b"ftyp" in head[:16]
    return any(head.startswith(sig) for sig in _MAGIC.get(content_type, ()))


@router.post(
    "", response_model=AttachmentOut, status_code=201, dependencies=[Depends(require_user)]
)
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

    # Reject on the declared size before reading anything, then read in bounded
    # chunks so a lying Content-Length cannot buffer an unbounded body into RAM.
    declared = file.size if file.size is not None else None
    if declared is not None and declared > MAX_BYTES:
        raise HTTPException(status_code=400, detail="File is larger than 10 MB.")

    contents = b""
    while True:
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        contents += chunk
        if len(contents) > MAX_BYTES:
            raise HTTPException(status_code=400, detail="File is larger than 10 MB.")
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    # The bytes must match the declared type, not just the header.
    if not _looks_like(file.content_type, contents[:16]):
        raise HTTPException(
            status_code=400,
            detail="The file's contents do not match its type. Please upload a real photo or PDF.",
        )

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


@router.get("/{attachment_id}/file", dependencies=[Depends(require_finance)])
def get_file(attachment_id: int, db: Session = Depends(get_db)) -> FileResponse:
    """Serve a stored receipt.

    Reading a receipt is finance data - it is a supplier invoice or a wage slip -
    so this is limited to the owner and the accountant, not every signed-in user.
    """
    attachment = db.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    path = Path(attachment.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file is missing")
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.filename,
        # Never let the browser sniff a stored file into something executable, and
        # never render it inline.
        headers={"X-Content-Type-Options": "nosniff", "Content-Disposition": "attachment"},
    )
