# app/schemas/esquema_orden_trabajo.py
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class MaterialRespuesta(BaseModel):
    """Detalle de la orden: columnas E a H."""
    model_config = ConfigDict(from_attributes=True)

    material: str
    descripcion_material: str
    um: str
    cantidad: Decimal


class ErrorValidacion(BaseModel):
    regla: str
    fila: Optional[int] = None
    columna: Optional[str] = None
    mensaje: str


class OrdenExistenteResumen(BaseModel):
    id: uuid.UUID
    estado: str
    version: int
    cargada_por: str
    cargada_en: datetime


class OrdenVistaPrevia(BaseModel):
    numero_orden: str
    descripcion: str            # producto
    pt: str                     # código del producto
    cantidad_pt: Optional[int]  # cantidad
    total_materiales: int
    situacion: str              # NUEVA | EXISTE | EN_DESARROLLO
    advertencias: list[str] = []
    materiales: list[MaterialRespuesta] = []
    existente: Optional[OrdenExistenteResumen] = None


class RespuestaValidacionArchivo(BaseModel):
    valido: bool
    archivo_nombre: str
    total_errores: int
    errores: list[ErrorValidacion]
    ordenes: list[OrdenVistaPrevia] = []


class OrdenResumen(BaseModel):
    id: uuid.UUID
    numero_orden: str
    descripcion: str
    pt: str
    cantidad_pt: int
    total_materiales: int
    estado: str
    version: int
    cargada_por: str
    cargada_en: datetime
    eliminada_por: Optional[str] = None
    eliminada_en: Optional[datetime] = None
    motivo_eliminacion: Optional[str] = None


class OrdenDetalle(OrdenResumen):
    creada_por: str
    creada_en: datetime
    motivo_actualizacion: Optional[str] = None
    desarrollo_por: Optional[str] = None
    desarrollo_en: Optional[datetime] = None
    materiales: list[MaterialRespuesta]


class OrdenCargadaResumen(BaseModel):
    id: uuid.UUID
    numero_orden: str
    version: int


class OrdenOmitida(BaseModel):
    numero_orden: str
    motivo: str


class RespuestaCargaOrdenes(BaseModel):
    mensaje: str
    cargadas: list[OrdenCargadaResumen]
    actualizadas: list[OrdenCargadaResumen]
    omitidas: list[OrdenOmitida]


class SolicitudMotivo(BaseModel):
    motivo: str = Field(..., max_length=2000)


class RespuestaDesarrollo(BaseModel):
    estado: str
    redireccion: str


class IndicadoresOrdenes(BaseModel):
    total: int
    cargadas: int
    en_desarrollo: int
    eliminadas: int
