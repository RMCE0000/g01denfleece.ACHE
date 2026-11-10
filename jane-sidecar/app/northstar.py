"""North Star. Insured is the guiding principle. Six aims sit beneath it."""

from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, Field

from app.config import get_settings


class NorthStar(BaseModel):
    """Insured orients the six aims. Energetic keeps its float and its profit boolean together."""

    automated: float = Field(ge=0.0, le=100.0)
    aesthetic: float = Field(ge=0.0, le=100.0)
    material: bool
    energetic: float = Field(ge=0.0, le=500.0)
    energetic_profitable: bool
    contained: bool
    utilized: float = Field(default=0.0, ge=0.0, le=100.0)
    insured: bool = False


class NorthStarSupporting(BaseModel):
    outside_aid_hours_per_week: float = Field(ge=0.0)
    material_surplus_profitable: bool


def _q2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def automated_pct_from_hours(hours: float, baseline: float | None = None) -> float:
    """Percentage reduction versus a full-manual week. 0 hours -> 100. Baseline hours -> 0."""
    if hours < 0:
        raise ValueError("hours cannot be negative")
    base = baseline if baseline is not None else get_settings().full_manual_hours_per_week
    if base <= 0:
        raise ValueError("baseline hours must be positive")
    raw = (1 - (hours / base)) * 100
    return _q2(max(0.0, min(100.0, raw)))


def clamp_aesthetic(value: float) -> float:
    if value < 0 or value > 100:
        raise ValueError("aesthetic must be between 0 and 100")
    return _q2(value)


def clamp_energetic(value: float) -> float:
    if value < 0 or value > 500:
        raise ValueError("energetic percent must be between 0 and 500")
    return _q2(value)


def clamp_utilized(value: float) -> float:
    if value < 0 or value > 100:
        raise ValueError("utilized must be between 0 and 100")
    return _q2(value)


def view_from_property(prop: dict) -> dict:
    star = NorthStar(
        automated=float(prop["northstar_automated_pct"]),
        aesthetic=float(prop["northstar_aesthetic_pct"]),
        material=bool(prop["northstar_material_independent"]),
        energetic=float(prop["northstar_energetic_pct"]),
        energetic_profitable=bool(prop["northstar_energetic_profitable"]),
        contained=bool(prop["northstar_contained_zero_waste"]),
        utilized=float(prop.get("northstar_utilized_pct") or 0),
        insured=bool(prop.get("northstar_insured", False)),
    )
    supporting = NorthStarSupporting(
        outside_aid_hours_per_week=float(prop["outside_aid_hours_per_week"]),
        material_surplus_profitable=bool(prop["material_surplus_profitable"]),
    )
    return {"northstar": star.model_dump(), "supporting": supporting.model_dump()}


DEFAULT_LEDGER = {
    "acreage": None,
    "soil_and_water": [],
    "energy_systems": [],
    "livestock_and_crops": [],
    "waste_containment": [],
    "skills_and_equipment": [],
    "active_goals": [],
}
