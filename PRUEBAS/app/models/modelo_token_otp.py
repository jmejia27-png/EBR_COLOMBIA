import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base_declarativa import Base

if TYPE_CHECKING:
    from app.models.modelo_usuario import Usuario

class TokenOTP(Base):
    __tablename__ = "tokens_otp"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    usuario_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    codigo_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    intentos_fallidos: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bloqueado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc), 
        nullable=False
    )

    # Relaciones ORM
    usuario: Mapped["Usuario"] = relationship("Usuario", back_populates="otps")