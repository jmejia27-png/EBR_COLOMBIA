from pydantic import BaseModel, Field

class SolicitudOTP(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, example="operador_demo")
    password: str = Field(..., min_length=4, example="Demo2026*")

class RespuestaOTP(BaseModel):
    exito: bool
    codigo_otp: str | None = None
    expira_en_segundos: int | None = None
    mensaje: str
    requiere_cambio_password: bool = False