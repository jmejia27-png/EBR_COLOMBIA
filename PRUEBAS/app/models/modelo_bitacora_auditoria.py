import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base_declarativa import Base

if TYPE_CHECKING:
    from app.models.modelo_usuario import Usuario

class AuditTrail(Base):
    __tablename__ = "audit_trail"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc), 
        nullable=False, 
        index=True
    )
    usuario_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    evento: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    modulo: Mapped[str] = mapped_column(String(50), nullable=False)
    entidad: Mapped[str] = mapped_column(String(50), nullable=False)
    entidad_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    accion: Mapped[str] = mapped_column(String(50), nullable=False)
    resultado: Mapped[str] = mapped_column(String(50), nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    device_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    datos_anteriores: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    datos_nuevos: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relaciones ORM
    usuario: Mapped[Optional["Usuario"]] = relationship("Usuario", back_populates="auditorias")