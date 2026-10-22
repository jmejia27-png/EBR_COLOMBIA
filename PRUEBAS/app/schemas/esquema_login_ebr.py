from typing import Optional
from pydantic import BaseModel, Field


class SolicitudLoginEBR(BaseModel):
    username: str
    password: str


class RespuestaLoginEBR(BaseModel):
    requiere_cambio_password: bool = False
    motivo_cambio: Optional[str] = None   # "PRIMER_INGRESO_O_RESTABLECIMIENTO" | "VENCIMIENTO_30_DIAS"
    mensaje: str


class SolicitudCambioPasswordEBR(BaseModel):
    username: str
    password_actual: str
    password_nueva: str = Field(..., min_length=4)


class RespuestaCambioPasswordEBR(BaseModel):
    exito: bool
    mensaje: str


class SolicitudCodigoEBR(BaseModel):
    username: str
    codigo: str = Field(..., min_length=4, max_length=4)


class RespuestaCodigoEBR(BaseModel):
    exito: bool
    mensaje: str
    access_token: Optional[str] = None
    expira_en_minutos: Optional[int] = None