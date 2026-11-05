# app/schemas/esquema_formato_ebr.py
# CU-04 Desarrollo de la orden · solicitudes del formato 03131 V2 y de la firma electrónica.
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field


class RegistroFormatoEntrada(BaseModel):
    linea_id: uuid.UUID
    exc: Optional[Any] = None
    dev: Optional[Any] = None
    rot: Optional[Any] = None
    cons: Optional[Any] = None
    lotes_materiales: Optional[str] = Field(default=None, max_length=2000)


class SolicitudGuardarFormato(BaseModel):
    revision: Optional[int] = None
    lote: Optional[str] = Field(default=None, max_length=200)
    fecha_vencimiento: Optional[str] = Field(default=None, max_length=20)
    linea: Optional[str] = Field(default=None, max_length=200)
    registros: list[RegistroFormatoEntrada] = Field(default_factory=list, max_length=2000)

    def como_dict(self) -> dict:
        datos = self.model_dump()
        datos["registros"] = [{**r, "linea_id": str(r["linea_id"])} for r in datos["registros"]]
        return datos


class SolicitudFirmaFormato(BaseModel):
    rol_firma: str = Field(max_length=40)
    firmante_id: uuid.UUID
    codigo: str = Field(min_length=1, max_length=10)
    revision: Optional[int] = None
