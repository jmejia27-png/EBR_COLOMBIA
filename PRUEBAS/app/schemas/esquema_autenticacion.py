from typing import Optional
from pydantic import BaseModel, Field

class SolicitudLogin(BaseModel):
    username: str
    password: str


class RespuestaLogin(BaseModel):
    access_token: Optional[str] = None          # CAMBIO: ahora opcional
    token_type: str = "bearer"
    expira_en_minutos: int = 0
    rol: str
    requiere_cambio_password: bool = False       # NUEVO


class SolicitudCambioPasswordObligatorio(BaseModel):
    username: str
    password_actual: str
    password_nueva: str = Field(..., min_length=4)


class RespuestaCambioPasswordObligatorio(BaseModel):
    exito: bool
    mensaje: str
    rol: str
    access_token: Optional[str] = None
    expira_en_minutos: Optional[int] = None
    codigo_otp: Optional[str] = None
    expira_en_segundos: Optional[int] = None