"""Structured receipt schema and a safe parser."""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError, field_validator


class LineItem(BaseModel):
    desc: str
    amount: float


class ReceiptFields(BaseModel):
    merchant: str
    date: str  # ISO yyyy-mm-dd
    amount: float = Field(ge=0)
    currency: str
    tax: float = Field(default=0.0, ge=0)
    line_items: list[LineItem] = []
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("currency")
    @classmethod
    def _currency_upper(cls, v: str) -> str:
        v = (v or "").upper()
        if len(v) != 3:
            raise ValueError("currency must be a 3-letter code")
        return v


def parse_or_none(data: object) -> "ReceiptFields | None":
    """Parse a dict into ReceiptFields, returning None on any validation error."""
    if not isinstance(data, dict):
        return None
    try:
        return ReceiptFields(**data)
    except (ValidationError, TypeError):
        return None
