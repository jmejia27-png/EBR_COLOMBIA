import uuid
import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base_declarativa import Base

if TYPE_CHECKING:
    from app.models.modelo_token_otp import TokenOTP
    from app.models.modelo_bitacora_auditoria import AuditTrail


class RolUsuario(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    nombre_completo: Mapped[str] = mapped_column(String(150), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    rol: Mapped[RolUsuario] = mapped_column(
        Enum(
            RolUsuario, 
            name="rol_usuario_enum",
            values_callable=lambda enum_cls: [miembro.value for miembro in enum_cls]
        ),
        default=RolUsuario.USER,
        nullable=False
    )

    requiere_cambio_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    password_actualizada_en: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    default=lambda: datetime.now(timezone.utc),
    nullable=False
    )

    otps: Mapped[list["TokenOTP"]] = relationship("TokenOTP", back_populates="usuario", cascade="all, delete-orphan")
    auditorias: Mapped[list["AuditTrail"]] = relationship("AuditTrail", back_populates="usuario")