# app/models/modelo_orden_trabajo.py
# CU-03 Cargar orden de trabajo: repositorio de órdenes de trabajo, sus materiales,
# sus versiones anteriores y los archivos de LX con los que se cargaron.
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    String, Integer, Text, DateTime, ForeignKey, LargeBinary, Numeric, Index, JSON, text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, deferred

from app.database.base_declarativa import Base

if TYPE_CHECKING:
    from app.models.modelo_usuario import Usuario


def _ahora():
    return datetime.now(timezone.utc)


class EstadoOrden:
    """Estados de la orden. Se guardan como texto para poder agregar los de CU-04 sin migrar tipos."""
    CARGADA = "CARGADA"              # cargada desde LX: se puede actualizar (nueva versión) o eliminar
    EN_DESARROLLO = "EN_DESARROLLO"  # se pulsó DESARROLLAR ORDEN: ya no se actualiza ni se elimina
    ELIMINADA = "ELIMINADA"          # eliminada con motivo: se conserva para trazabilidad

    TODOS = (CARGADA, EN_DESARROLLO, ELIMINADA)
    ACTIVOS = (CARGADA, EN_DESARROLLO)


class ArchivoCargaOrden(Base):
    """Archivo Excel de LX tal como se subió. Un archivo puede contener varias órdenes."""
    __tablename__ = "archivos_carga_orden"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    hash_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    contenido: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    cargado_por_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    cargado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora, nullable=False)


class OrdenTrabajo(Base):
    """Encabezado de la orden de trabajo (columnas A a D de la hoja BOM)."""
    __tablename__ = "ordenes_trabajo"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # Información general (hoja BOM)
    numero_orden: Mapped[str] = mapped_column(String(30), nullable=False, index=True)    # columna A
    pt: Mapped[str] = mapped_column(String(50), nullable=False)                         # columna B: código del producto
    descripcion: Mapped[str] = mapped_column(String(255), nullable=False)               # columna C: producto
    cantidad_pt: Mapped[int] = mapped_column(Integer, nullable=False)                   # columna D: cantidad
    total_materiales: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    estado: Mapped[str] = mapped_column(String(20), nullable=False, default=EstadoOrden.CARGADA, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Primera carga (versión 1)
    creada_por_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora, nullable=False)
    # Carga de la versión vigente (igual a la creación mientras sea versión 1)
    cargada_por_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    cargada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora, nullable=False, index=True)
    motivo_actualizacion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    archivo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("archivos_carga_orden.id"), nullable=False)

    # Eliminación
    eliminada_por_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    eliminada_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_eliminacion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Inicio del desarrollo (paso a CU-04)
    desarrollo_por_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    desarrollo_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    lineas: Mapped[list["LineaMaterialOrden"]] = relationship(
        back_populates="orden", cascade="all, delete-orphan", order_by="LineaMaterialOrden.posicion"
    )
    versiones: Mapped[list["VersionOrdenTrabajo"]] = relationship(
        back_populates="orden", cascade="all, delete-orphan", order_by="VersionOrdenTrabajo.version"
    )
    creada_por: Mapped["Usuario"] = relationship(foreign_keys=[creada_por_id])
    cargada_por: Mapped["Usuario"] = relationship(foreign_keys=[cargada_por_id])
    eliminada_por: Mapped[Optional["Usuario"]] = relationship(foreign_keys=[eliminada_por_id])
    desarrollo_por: Mapped[Optional["Usuario"]] = relationship(foreign_keys=[desarrollo_por_id])

    __table_args__ = (
        # Un número de orden solo puede estar UNA vez entre las órdenes no eliminadas.
        Index(
            "uq_ordenes_trabajo_numero_activa",
            "numero_orden",
            unique=True,
            postgresql_where=text("estado <> 'ELIMINADA'"),
            sqlite_where=text("estado <> 'ELIMINADA'"),
        ),
    )


class LineaMaterialOrden(Base):
    """Detalle de la orden: un material por fila (columnas E a H de la hoja BOM)."""
    __tablename__ = "lineas_material_orden"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    orden_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ordenes_trabajo.id", ondelete="CASCADE"), nullable=False, index=True
    )
    posicion: Mapped[int] = mapped_column(Integer, nullable=False)          # orden en el archivo (no se muestra)
    material: Mapped[str] = mapped_column(String(50), nullable=False)        # columna E
    descripcion_material: Mapped[str] = mapped_column(String(255), nullable=False)  # columna F
    um: Mapped[str] = mapped_column(String(20), nullable=False)              # columna G
    cantidad: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)  # columna H

    orden: Mapped["OrdenTrabajo"] = relationship(back_populates="lineas")


class VersionOrdenTrabajo(Base):
    """Copia de una versión anterior de la orden, guardada al reemplazarla por una nueva."""
    __tablename__ = "versiones_orden_trabajo"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    orden_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ordenes_trabajo.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    datos: Mapped[dict] = mapped_column(JSON, nullable=False)  # encabezado + materiales de esa versión
    archivo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("archivos_carga_orden.id"), nullable=False)
    cargada_por_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    cargada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reemplazada_por_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    reemplazada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora, nullable=False)
    motivo_reemplazo: Mapped[str] = mapped_column(Text, nullable=False)

    orden: Mapped["OrdenTrabajo"] = relationship(back_populates="versiones")
