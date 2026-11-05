# app/models/modelo_formato_ebr.py
# CU-04 Desarrollo de la orden de trabajo.
#   DocumentoFormato       -> un formato del EBR diligenciado para una orden (primero: 03131 V2 "Orden de trabajo").
#   RegistroLineaFormato   -> datos editables de cada material de la orden (EXC, DEV, ROT, CONS, análisis).
#   FirmaElectronica       -> firma electrónica genérica (usuario + token), reutilizable por cualquier formato futuro.
# Los datos que vienen de LX (orden y materiales, CU-03) NO se copian ni se editan aquí: se leen de
# ordenes_trabajo / lineas_material_orden.
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Date, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.database.base_declarativa import Base

if TYPE_CHECKING:
    from app.models.modelo_orden_trabajo import LineaMaterialOrden, OrdenTrabajo
    from app.models.modelo_usuario import Usuario


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class EstadoFormato:
    BORRADOR = "BORRADOR"                    # se está diligenciando
    FIRMADO_DIGITADOR = "FIRMADO_DIGITADOR"  # firmó "Digitado por": los datos quedan bloqueados
    COMPLETADO = "COMPLETADO"                # firmó el Encargado o Supervisor Global: PDF definitivo generado
    TODOS = (BORRADOR, FIRMADO_DIGITADOR, COMPLETADO)


class DocumentoFormato(Base):
    __tablename__ = "documentos_formato"
    __table_args__ = (UniqueConstraint("orden_id", "codigo_formato", name="uq_documento_formato_orden"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    orden_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ordenes_trabajo.id"), nullable=False, index=True)
    codigo_formato: Mapped[str] = mapped_column(String(20), nullable=False)    # 03131
    version_formato: Mapped[str] = mapped_column(String(10), nullable=False)   # V2
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default=EstadoFormato.BORRADOR)
    version_orden: Mapped[int] = mapped_column(Integer, nullable=False)        # versión de la orden de LX usada

    # Encabezado diligenciado por el usuario
    lote: Mapped[Optional[str]] = mapped_column(String(30))
    fecha_vencimiento: Mapped[Optional[date]] = mapped_column(Date)
    linea: Mapped[Optional[str]] = mapped_column(String(30))
    fecha_documento: Mapped[date] = mapped_column(Date, nullable=False)        # fecha del primer guardado (automática)

    # Control de concurrencia: cada guardado incrementa el número
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    creado_por_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_ahora)
    actualizado_por_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_ahora)
    completado_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # PDF definitivo (solo cuando el formato tiene todas sus firmas)
    pdf: Mapped[Optional[bytes]] = deferred(mapped_column(LargeBinary))
    pdf_hash_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    pdf_generado_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    orden: Mapped["OrdenTrabajo"] = relationship("OrdenTrabajo")
    registros: Mapped[list["RegistroLineaFormato"]] = relationship(
        "RegistroLineaFormato", back_populates="documento", cascade="all, delete-orphan")
    creado_por: Mapped["Usuario"] = relationship("Usuario", foreign_keys=[creado_por_id])
    actualizado_por: Mapped["Usuario"] = relationship("Usuario", foreign_keys=[actualizado_por_id])


class RegistroLineaFormato(Base):
    __tablename__ = "registros_linea_formato"
    __table_args__ = (UniqueConstraint("documento_id", "linea_id", name="uq_registro_linea_formato"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    documento_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documentos_formato.id", ondelete="CASCADE"), nullable=False, index=True)
    linea_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lineas_material_orden.id"), nullable=False)
    exc: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    dev: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    rot: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    cons: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    lotes_materiales: Mapped[Optional[str]] = mapped_column(String(500))

    documento: Mapped["DocumentoFormato"] = relationship("DocumentoFormato", back_populates="registros")
    linea: Mapped["LineaMaterialOrden"] = relationship("LineaMaterialOrden")


class FirmaElectronica(Base):
    """Firma electrónica genérica: identifica el registro firmado por (entidad, entidad_id) y el
    rol de la firma dentro de él. Conserva el nombre completo y el usuario tal como estaban al firmar."""
    __tablename__ = "firmas_electronicas"
    __table_args__ = (UniqueConstraint("entidad", "entidad_id", "rol_firma", name="uq_firma_rol_registro"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entidad: Mapped[str] = mapped_column(String(50), nullable=False)          # p. ej. documentos_formato
    entidad_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    rol_firma: Mapped[str] = mapped_column(String(40), nullable=False)        # DIGITADO_POR, SUPERVISOR
    significado: Mapped[str] = mapped_column(String(120), nullable=False)     # texto que aparece en el documento
    usuario_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    nombre_completo: Mapped[str] = mapped_column(String(150), nullable=False)
    firmado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_ahora)
    hash_datos: Mapped[str] = mapped_column(String(64), nullable=False)       # SHA-256 del contenido firmado
    token_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("tokens_otp.id", ondelete="SET NULL"))
    registrada_por_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), nullable=False)  # sesión desde la que se firmó
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))

    usuario: Mapped["Usuario"] = relationship("Usuario", foreign_keys=[usuario_id])
