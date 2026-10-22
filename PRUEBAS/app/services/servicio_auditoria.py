# app/services/servicio_auditoria.py
import logging
import uuid
from typing import Optional, Dict, Any, Union
from sqlalchemy.orm import Session

from app.models.modelo_bitacora_auditoria import AuditTrail

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("audit_trail")


class ServicioAuditoria:

    @staticmethod
    def registrar_evento(
        db: Session,
        evento: str,
        modulo: str,
        accion: str,
        resultado: str,
        usuario_id: Optional[Union[uuid.UUID, str]] = None,
        entidad: Optional[str] = None,
        entidad_id: Optional[str] = None,
        ip_address: str = "127.0.0.1",
        device_info: Optional[str] = None,
        datos_anteriores: Optional[Dict[str, Any]] = None,
        datos_nuevos: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Registra eventos de auditoría transversalmente en la aplicación,
        persistiendo directamente en la tabla PostgreSQL audit_trail.

        El registro de auditoría NUNCA debe romper el flujo de negocio que lo
        invoca: cualquier error aquí se captura, se loguea y se retorna False,
        sin propagar la excepción hacia arriba.
        """
        try:
            nuevo_evento = AuditTrail(
                usuario_id=usuario_id,
                evento=evento,
                modulo=modulo,
                entidad=entidad or "N/A",
                entidad_id=entidad_id,
                accion=accion,
                resultado=resultado,
                ip_address=ip_address,
                device_info=device_info,
                datos_anteriores=datos_anteriores,
                datos_nuevos=datos_nuevos
            )
            db.add(nuevo_evento)
            db.commit()
            db.refresh(nuevo_evento)

            logger.info(
                f"[AUDIT] [{modulo}] {evento} - Accion: {accion} - "
                f"Resultado: {resultado} - User: {usuario_id}"
            )
            return True

        except Exception as error:
            db.rollback()
            logger.error(
                f"[AUDIT-ERROR] No se pudo persistir el evento '{evento}' "
                f"para el usuario {usuario_id}: {error}"
            )
            return False