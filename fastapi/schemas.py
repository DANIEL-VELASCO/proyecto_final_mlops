"""Schemas Pydantic — alineados al payload que envía Streamlit y Locust.

Cualquier cambio en estos schemas exige notificar a P3 (rompe contrato con Streamlit/Locust).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class PropertyRequest(BaseModel):
    """Datos de entrada para inferir el precio de una propiedad."""

    brokered_by: str = Field(..., description="Agencia o corredor (codificado)")
    status: str = Field(..., description='Estado, ej. "for_sale" o "for_build"')
    bed: int = Field(..., ge=0, le=50, description="Habitaciones")
    bath: int = Field(..., ge=0, le=50, description="Baños")
    acre_lot: float = Field(..., ge=0.0, le=10_000.0, description="Tamaño del terreno (acres)")
    street: str = Field(..., description="Dirección codificada")
    city: str = Field(..., description="Ciudad")
    state: str = Field(..., description="Estado / región")
    zip_code: int = Field(..., ge=0, le=999_999, description="Código postal")
    house_size: int = Field(..., ge=0, le=1_000_000, description="Área habitable (sq ft)")
    prev_sold_date: Optional[date] = Field(
        None, description="Fecha de venta anterior (opcional)"
    )

    @field_validator("status")
    @classmethod
    def lower_status(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("brokered_by", "street", "city", "state")
    @classmethod
    def strip_strings(cls, v: str) -> str:
        return v.strip()

    def to_model_payload(self) -> dict:
        """Diccionario consumible por el preprocesador (preprocess.prepare_inference_frame)."""
        payload = self.model_dump()
        if payload["prev_sold_date"] is not None:
            payload["prev_sold_date"] = payload["prev_sold_date"].isoformat()
        return payload


class PredictionResponse(BaseModel):
    """Respuesta que consume Streamlit (campos price, model_version, model_alias)."""

    price: float
    model_version: str
    model_alias: str
    inference_id: Optional[str] = None
    timestamp: str


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    model_version: Optional[str] = None
    model_alias: Optional[str] = None


class ReloadRequest(BaseModel):
    force: bool = False


class ReloadResponse(BaseModel):
    reloaded: bool
    previous_version: Optional[str]
    current_version: Optional[str]
    message: str
