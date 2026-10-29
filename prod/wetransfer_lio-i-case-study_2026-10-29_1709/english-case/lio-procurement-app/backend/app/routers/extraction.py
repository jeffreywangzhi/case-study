import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_membership, get_current_user
from app.db.session import get_db
from app.models import Organization, OrganizationMember, Profile
from app.routers.pdf import MAX_PDF_BYTES
from app.schemas.extraction import ExtractionRequest, ExtractionResponse
from app.services.extraction import extract_vendor_data, extract_vendor_data_from_pdf
from app.services.pdf import is_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/extraction", tags=["extraction"])


@router.post("", response_model=ExtractionResponse, response_model_by_alias=True,
             dependencies=[Depends(get_current_user)])
def extract(payload: ExtractionRequest, db: Session = Depends(get_db)) -> ExtractionResponse:
    """Extract structured vendor data from PDF text via OpenAI (text only, no images).

    Kept for API compatibility; the upload flow uses ``POST /extraction/pdf``.
    Returns ``{success, data?, error?, missingFields?, warnings, status}`` — errors
    are part of the payload, not HTTP errors, so the UI can show partial results.
    """
    return extract_vendor_data(payload.text, db)


@router.post("/pdf", response_model=ExtractionResponse, response_model_by_alias=True)
async def extract_pdf(
    file: UploadFile,
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ExtractionResponse:
    """Extract vendor data from an uploaded quote PDF (layout text + page images).

    The caller's organization name helps catch a vendor/recipient mix-up, and the
    requester's department pre-fills the department field.
    """
    pdf_bytes = await file.read()
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="PDF exceeds the 10MB limit",
        )
    if not is_pdf(pdf_bytes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload a PDF file"
        )

    organization = db.get(Organization, membership.organization_id)
    profile = db.get(Profile, membership.user_id)
    try:
        return extract_vendor_data_from_pdf(
            pdf_bytes,
            db,
            organization_names=[organization.name] if organization else [],
            requester_department=profile.department if profile else None,
        )
    except Exception:  # noqa: BLE001 — unreadable/corrupt PDF (model errors are in the envelope)
        logger.exception("Failed to read uploaded PDF %s", file.filename)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Failed to parse PDF",
        )
