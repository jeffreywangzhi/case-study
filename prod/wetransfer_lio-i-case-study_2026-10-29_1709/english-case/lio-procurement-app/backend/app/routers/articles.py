from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_membership
from app.db.session import get_db
from app.models import Article, OrganizationMember
from app.schemas.articles import (
    ArticleOut,
    ArticlePage,
    CatalogMatchRequest,
    CatalogMatchResponse,
    CatalogSuggestion,
)
from app.services import catalog_matching

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("/suggest", response_model=list[CatalogSuggestion])
def suggest_articles(
    q: str = Query(min_length=2, max_length=200, description="What the requester is typing"),
    limit: int = Query(default=5, ge=1, le=10),
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[CatalogSuggestion]:
    """Typeahead: catalog items with negotiated prices that clearly match ``q``.

    Fast path (keyword + embedding retrieval, no model check), for the manual form.
    """
    return catalog_matching.suggest(db, membership.organization_id, q, limit)


@router.post("/match", response_model=CatalogMatchResponse)
def match_articles(
    payload: CatalogMatchRequest,
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> CatalogMatchResponse:
    """Catalog agreements for each request line, checked by the model, with savings vs the
    quoted prices. Also reports whether the quote's vendor is in the supplier master.
    """
    return catalog_matching.match_lines(
        db, membership.organization_id, payload.lines,
        vendor_name=payload.vendor_name, vat_id=payload.vat_id,
    )


@router.get("", response_model=ArticlePage)
def list_articles(
    search: str | None = Query(
        default=None, description="Filter by description or article number (case-insensitive)"
    ),
    supplier_id: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ArticlePage:
    filters = [Article.organization_id == membership.organization_id]
    if search:
        term = f"%{search}%"
        filters.append(
            or_(Article.description.ilike(term), Article.article_number.ilike(term))
        )
    if supplier_id:
        filters.append(Article.supplier_id == supplier_id)

    total = db.scalar(
        select(func.count()).select_from(Article).where(*filters)
    ) or 0

    stmt = (
        select(Article)
        .where(*filters)
        .options(joinedload(Article.supplier))
        .order_by(Article.article_number)
        .offset(offset)
        .limit(limit)
    )
    items = [
        ArticleOut(
            id=a.id,
            article_number=a.article_number,
            supplier_id=a.supplier_id,
            supplier_name=a.supplier.name if a.supplier else None,
            description=a.description,
            unit_price=a.unit_price,
            currency=a.currency,
            unit=a.unit,
            quantity=a.quantity,
            created_at=a.created_at,
        )
        for a in db.scalars(stmt)
    ]
    return ArticlePage(items=items, total=total, limit=limit, offset=offset)


@router.get("/count")
def count_articles(
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    total = (
        db.scalar(
            select(func.count())
            .select_from(Article)
            .where(Article.organization_id == membership.organization_id)
        )
        or 0
    )
    return {"count": total}
