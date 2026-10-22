import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict

from app.models.modelo_usuario import RolUsuario


class UsuarioCrear(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    nombre_completo: str = Field(..., min_length=3, max_length=150)
    password: str = Field(..., min_length=4)
    rol: RolUsuario = RolUsuario.USER


class UsuarioActualizar(BaseModel):
    username: Optional[str] = Field(default=None, min_length=3, max_length=50)
    activo: Optional[bool] = None


class UsuarioRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: str
    nombre_completo: str
    rol: RolUsuario
    activo: bool
    creado_en: datetime

class UsuarioRestablecerPassword(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password_temporal: str = Field(..., min_length=4)    
