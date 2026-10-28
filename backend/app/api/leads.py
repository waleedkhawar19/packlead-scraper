from __future__ import annotations

from datetime import datetime, time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.job import utcnow
from app.models.lead import Lead
from app.schemas.job import Page
from app.schemas.lead import (
    BulkIds, BulkTag, ClassifyRequest, LeadCreate, LeadDetail, LeadFilters, LeadOut, LeadUpdate, ValidateRequest,
)
from app.services import app_settings, category_classifier
from app.services.email_validator import ALL_STATUSES, EmailValidator, check_syntax, is_role_based

router = APIRouter(prefix="/api/leads", tags=["leads"])

SORTABLE = {
    "business_name": Lead.business_name, "email": Lead.email, "website": Lead.website, "category": Lead.category,
    "city": Lead.city, "state": Lead.state, "country": Lead.country, "phone": Lead.phone, "source_type": Lead.source_type,
    "source_filename": Lead.source_filename, "collected_at": Lead.collected_at, "verification_status": Lead.verification_status,
    "email_domain": Lead.email_domain, "id": Lead.id,
}


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def apply_filters(stmt, f: LeadFilters):  # noqa: ANN001
    if f.only_test:
        stmt = stmt.where(Lead.is_test.is_(True))
    elif not f.include_test:
        stmt = stmt.where(Lead.is_test.is_(False))
    if f.q:
        like = _like(f.q.strip().lower())
        stmt = stmt.where(or_(*(func.lower(c).like(like, escape="\\") for c in (Lead.email, Lead.business_name, Lead.website, Lead.notes, Lead.city, Lead.state, Lead.phone, Lead.tags))))
    for col, val in ((Lead.category, f.category), (Lead.state, f.state), (Lead.city, f.city), (Lead.email_domain, f.domain),
                     (Lead.source_type, f.source_type), (Lead.verification_status, f.verification_status)):
        if val:
            stmt = stmt.where(col == val)
    if f.date_from:
        stmt = stmt.where(Lead.collected_at >= datetime.combine(f.date_from, time.min))
    if f.date_to:
        stmt = stmt.where(Lead.collected_at <= datetime.combine(f.date_to, time.max))
    if f.has_website is True:
        stmt = stmt.where(and_(Lead.website.is_not(None), Lead.website != ""))
    elif f.has_website is False:
        stmt = stmt.where(or_(Lead.website.is_(None), Lead.website == ""))
    if f.role_based is not None:
        stmt = stmt.where(Lead.is_role_based.is_(f.role_based))
    if f.tag:
        stmt = stmt.where(func.lower(Lead.tags).like(_like(f.tag.lower()), escape="\\"))
    if f.job_id:
        stmt = stmt.where(Lead.job_id == f.job_id)
    terms = [t.strip().lower() for t in (f.keywords or "").split(",") if t.strip()]
    if terms:
        conds = [or_(*(func.lower(c).like(_like(t), escape="\\") for c in (Lead.context_text, Lead.business_name, Lead.category, Lead.notes))) for t in terms]
        stmt = stmt.where(and_(*conds) if f.keyword_mode == "all" else or_(*conds))
    return stmt


def lead_filters(
    q: Optional[str] = None, category: Optional[str] = None, state: Optional[str] = None, city: Optional[str] = None,
    domain: Optional[str] = None, source_type: Optional[str] = None, verification_status: Optional[str] = None,
    date_from: Optional[str] = None, date_to: Optional[str] = None, has_website: Optional[bool] = None,
    role_based: Optional[bool] = None, tag: Optional[str] = None, job_id: Optional[int] = None,
    keywords: Optional[str] = None, keyword_mode: str = "any", include_test: bool = False, only_test: bool = False,
) -> LeadFilters:
    try:
        return LeadFilters(q=q, category=category, state=state, city=city, domain=domain, source_type=source_type,
                           verification_status=verification_status, date_from=date_from or None, date_to=date_to or None,
                           has_website=has_website, role_based=role_based, tag=tag, job_id=job_id, keywords=keywords,
                           keyword_mode=keyword_mode if keyword_mode in ("any", "all") else "any", include_test=include_test, only_test=only_test)
    except ValueError as exc:
        raise HTTPException(422, f"Invalid filter: {exc}")


def select_leads(db: Session, f: LeadFilters, ids: Optional[List[int]] = None, with_sources: bool = False):
    stmt = apply_filters(select(Lead), f)
    if ids is not None:
        stmt = stmt.where(Lead.id.in_(ids))
    if with_sources:
        stmt = stmt.options(selectinload(Lead.sources))
    return stmt


@router.get("", response_model=Page)
def list_leads(
    f: LeadFilters = Depends(lead_filters), sort_by: str = "collected_at", sort_dir: str = "desc",
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=500), db: Session = Depends(get_db),
):
    stmt = apply_filters(select(Lead), f)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = SORTABLE.get(sort_by, Lead.collected_at)
    order = col.asc() if sort_dir == "asc" else col.desc()
    rows = db.scalars(stmt.order_by(order, Lead.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    terms = [t.strip() for t in (f.keywords or "").split(",") if t.strip()]
    items = []
    for r in rows:
        out = LeadOut.model_validate(r)
        if terms:
            hay = " ".join(filter(None, [r.context_text, r.business_name, r.category, r.notes]))
            out.matched_keywords = category_classifier.find_keyword_matches(hay, terms)
        items.append(out)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/filters")
def filter_options(include_test: bool = False, db: Session = Depends(get_db)):
    """Distinct values for the filter drop-downs."""
    base = select(Lead)
    if not include_test:
        base = base.where(Lead.is_test.is_(False))
    sub = base.subquery()

    def distinct_values(col, limit=500):  # noqa: ANN001
        return [v for (v,) in db.execute(select(col).select_from(sub).where(col.is_not(None), col != "").distinct().order_by(col).limit(limit))]

    domains = [d for d, _ in db.execute(select(sub.c.email_domain, func.count().label("n")).group_by(sub.c.email_domain).order_by(func.count().desc()).limit(300))]
    return {
        "categories": distinct_values(sub.c.category), "states": distinct_values(sub.c.state), "cities": distinct_values(sub.c.city),
        "domains": domains, "source_types": distinct_values(sub.c.source_type), "verification_statuses": ALL_STATUSES,
        "has_test_data": bool(db.scalar(select(func.count()).select_from(Lead).where(Lead.is_test.is_(True)))),
    }


@router.get("/{lead_id}", response_model=LeadDetail)
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.scalars(select(Lead).where(Lead.id == lead_id).options(selectinload(Lead.sources))).first()
    if not lead:
        raise HTTPException(404, "Lead not found")
    return lead


def _clean(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    return v or None


@router.post("", response_model=LeadOut, status_code=201)
def create_lead(body: LeadCreate, db: Session = Depends(get_db)):
    """Add a lead by hand (source type 'manual')."""
    ok, why = check_syntax(body.email)
    if not ok:
        raise HTTPException(422, f"Invalid email: {why}")
    if db.scalar(select(Lead.id).where(Lead.email == body.email)):
        raise HTTPException(409, "A lead with this email already exists")
    data = {k: _clean(v) for k, v in body.model_dump(exclude={"email", "verification_status"}).items()}
    lead = Lead(email=body.email, original_email=body.email, email_domain=body.email.split("@", 1)[1], is_role_based=is_role_based(body.email),
                source_type="manual", collected_at=utcnow(), verification_status="Syntax Valid",
                verification_detail="Syntax is valid. DNS was not checked; mailbox existence is not confirmed.", **data)
    if lead.category:
        lead.category_source = "manual"
    db.add(lead)
    db.commit()
    return lead


@router.patch("/{lead_id}", response_model=LeadOut)
def update_lead(lead_id: int, body: LeadUpdate, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    changes = body.model_dump(exclude_unset=True)
    if "verification_status" in changes and changes["verification_status"] not in ALL_STATUSES:
        raise HTTPException(422, f"verification_status must be one of {ALL_STATUSES}")
    for k, v in changes.items():
        setattr(lead, k, _clean(v) if k != "verification_status" else v)
    if "category" in changes:
        lead.category_source = "manual" if lead.category else None
    db.commit()
    return lead


@router.post("/bulk-delete")
def bulk_delete(body: BulkIds, db: Session = Depends(get_db)):
    removed = 0
    for i in range(0, len(body.ids), 500):
        removed += db.execute(delete(Lead).where(Lead.id.in_(body.ids[i : i + 500]))).rowcount or 0
    db.commit()
    return {"deleted": removed}


@router.post("/bulk-tag")
def bulk_tag(body: BulkTag, db: Session = Depends(get_db)):
    new = [t.strip() for t in body.tags if t.strip()]
    changed = 0
    for lead in db.scalars(select(Lead).where(Lead.id.in_(body.ids))):
        current = [t.strip() for t in (lead.tags or "").split(",") if t.strip()]
        if body.mode == "set":
            result = new
        elif body.mode == "remove":
            result = [t for t in current if t.lower() not in {n.lower() for n in new}]
        else:
            result = current + [t for t in new if t.lower() not in {c.lower() for c in current}]
        lead.tags = ", ".join(result)[:500] or None
        changed += 1
    db.commit()
    return {"updated": changed}


@router.post("/validate")
async def validate_leads(body: ValidateRequest, db: Session = Depends(get_db)):
    """Re-run syntax + MX checks (DNS only; never contacts a mail server). Max 500 leads per call."""
    stmt = select(Lead)
    if body.ids:
        stmt = stmt.where(Lead.id.in_(body.ids))
    if body.only_unverified:
        stmt = stmt.where(Lead.verification_status.in_(("Syntax Valid", "Unverified")))
    leads = db.scalars(stmt.order_by(Lead.id).limit(500)).all()
    validator = EmailValidator()
    results = await validator.validate_many([l.email for l in leads], check_mx=body.check_mx)
    summary: Dict[str, int] = {}
    for lead in leads:
        r = results.get(lead.email)
        if r:
            lead.verification_status, lead.verification_detail = r.status, r.detail
            summary[r.status] = summary.get(r.status, 0) + 1
    db.commit()
    return {"checked": len(leads), "by_status": summary}


@router.post("/classify")
def classify_leads(body: ClassifyRequest, db: Session = Depends(get_db)):
    """Suggest categories from saved page text. Manually set categories are never overwritten."""
    stmt = select(Lead).where(Lead.context_text.is_not(None))
    if body.ids:
        stmt = stmt.where(Lead.id.in_(body.ids))
    extra = app_settings.custom_keywords(db)
    classified = 0
    for lead in db.scalars(stmt):
        if lead.category_source == "manual":
            continue
        guess = category_classifier.classify(lead.context_text or "", extra)
        if guess:
            lead.category, lead.category_source, lead.category_evidence = guess["category"], "auto", guess
            classified += 1
    db.commit()
    return {"classified": classified}
