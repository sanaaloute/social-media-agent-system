"""Brand routes — define the user's niche/domain for guided research (§3.2).

A Brand's niche + keywords drive the Researcher Agent's hot-topic
discovery when a task is created without an explicit topic.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from src.core.database.engine import get_session
from src.core.models import Brand
from src.services import _audit

router = APIRouter(prefix="/brands", tags=["brands"])


class BrandCreate(BaseModel):
    name: str
    niche: str
    keywords: List[str] = Field(default_factory=list)
    tone: str = ""
    platforms: List[str] = Field(default_factory=list)
    autopilot: bool = False


@router.post("", status_code=201, response_model=Brand)
def create_brand(payload: BrandCreate, session: Session = Depends(get_session)):
    if not payload.name.strip() or not payload.niche.strip():
        raise HTTPException(400, "Brand name and niche are required")
    brand = Brand(
        name=payload.name.strip(),
        niche=payload.niche.strip(),
        keywords=[k.strip() for k in payload.keywords if k.strip()],
        tone=payload.tone.strip(),
        platforms=[p.strip().lower() for p in payload.platforms if p.strip()],
        autopilot=payload.autopilot,
    )
    session.add(brand)
    _audit(
        session,
        actor="operator",
        action="brand_created",
        detail={"name": brand.name, "niche": brand.niche},
    )
    session.commit()
    session.refresh(brand)
    return brand


@router.get("", response_model=List[Brand])
def list_brands(session: Session = Depends(get_session)):
    return list(session.exec(select(Brand).order_by(Brand.created_at)).all())


@router.delete("/{brand_id}")
def delete_brand(brand_id: str, session: Session = Depends(get_session)):
    brand = session.get(Brand, brand_id)
    if brand is None:
        raise HTTPException(404, f"Brand {brand_id!r} not found")
    session.delete(brand)
    session.commit()
    return {"deleted": brand_id}
