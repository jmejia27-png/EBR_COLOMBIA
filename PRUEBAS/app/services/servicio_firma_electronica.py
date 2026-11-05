# app/services/servicio_firma_electronica.py
# Firma electrónica genérica del EBR (CU-04 y formatos futuros).
#
# Flujo: el firmante se selecciona en el panel de usuarios, genera su token en el Generador de Tokens
# (CU-01, valida usuario y contraseña) y lo digita para firmar. El token se valida con las mismas reglas
# del Login EBR: debe ser del firmante, coincidir, no estar usado ni vencido (60 s); tres intentos
# incorrectos lo bloquean. Una firma correcta deja nombre completo, usuario, fecha y hora exacta.
import uuid
from datetime import datetime, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.modelo_formato_ebr import FirmaElectronica
from app.models.modelo_token_otp import TokenOTP
from app.models.modelo_usuario import RolUsuario, Usuario
from app.services.servicio_auditoria import ServicioAuditoria

ph = PasswordHasher()
MAX_INTENTOS_TOKEN = 3


class FirmaInvalidaError(Exception):
    """El firmante o el token no permiten registrar la firma."""


class TokenFirmaBloqueadoError(FirmaInvalidaError):
    """El token se bloqueó tras tres intentos incorrectos: se debe generar uno nuevo."""


class ServicioFirmaElectronica:

    @staticmethod
    def listar_firmantes(db: Session, busqueda: Optional[str] = None, limite: int = 200) -> list[Usuario]:
        """Usuarios activos para el panel de firma. Los USER aparecen, pero no pueden firmar."""
        consulta = db.query(Usuario).filter(Usuario.activo.is_(True))
        if busqueda and busqueda.strip():
            patron = f"%{busqueda.strip().lower()}%"
            consulta = consulta.filter(or_(func.lower(Usuario.username).like(patron), func.lower(Usuario.nombre_completo).like(patron)))
        return consulta.order_by(Usuario.nombre_completo).limit(limite).all()

    @staticmethod
    def validar_firmante(db: Session, firmante_id: uuid.UUID) -> Usuario:
        firmante = db.query(Usuario).filter(Usuario.id == firmante_id).first()
        if not firmante or not firmante.activo:
            raise FirmaInvalidaError("El usuario seleccionado no existe o está inactivo.")
        if firmante.rol != RolUsuario.ADMIN:
            raise FirmaInvalidaError("Solo un usuario ADMIN puede firmar. Seleccione un usuario con rol ADMIN.")
        return firmante

    @staticmethod
    def validar_token(db: Session, firmante: Usuario, codigo: str, contexto: dict, sesion: Usuario, ip: str) -> TokenOTP:
        """Valida el token del firmante. Si es correcto lo marca como usado (sin confirmar la transacción:
        quien firma confirma la firma y el token juntos). Los rechazos se confirman y auditan aquí."""
        base_auditoria = dict(usuario_id=sesion.id, modulo="FIRMA", entidad="tokens_otp", accion="FIRMAR", ip_address=ip)
        datos = {**contexto, "firmante": firmante.username}
        codigo = (codigo or "").strip()
        if not (len(codigo) == 4 and codigo.isdigit()):
            raise FirmaInvalidaError("El token debe tener 4 dígitos.")

        token = (
            db.query(TokenOTP)
            .filter(TokenOTP.usuario_id == firmante.id, TokenOTP.usado.is_(False), TokenOTP.bloqueado.is_(False))
            .order_by(TokenOTP.creado_en.desc())
            .first()
        )
        if not token:
            ServicioAuditoria.registrar_evento(db=db, evento="FIRMA_TOKEN_NO_ENCONTRADO", resultado="ERROR_SIN_TOKEN_VIGENTE",
                                               datos_nuevos=datos, **base_auditoria)
            raise FirmaInvalidaError(f"{firmante.nombre_completo} no tiene un token vigente. Genérelo en el Generador de Tokens.")

        expira = token.expira_en if token.expira_en.tzinfo else token.expira_en.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expira:
            ServicioAuditoria.registrar_evento(db=db, evento="FIRMA_TOKEN_EXPIRADO", resultado="ERROR_TOKEN_EXPIRADO",
                                               entidad_id=str(token.id), datos_nuevos=datos, **base_auditoria)
            raise FirmaInvalidaError("El token expiró (vigencia de 60 segundos). Genere uno nuevo.")

        try:
            ph.verify(token.codigo_hash, codigo)
        except VerifyMismatchError:
            token.intentos_fallidos = (token.intentos_fallidos or 0) + 1
            token.bloqueado = token.intentos_fallidos >= MAX_INTENTOS_TOKEN
            db.commit()
            ServicioAuditoria.registrar_evento(
                db=db, evento="FIRMA_TOKEN_INCORRECTO", resultado="ERROR_TOKEN_INCORRECTO", entidad_id=str(token.id),
                datos_nuevos={**datos, "intentos_fallidos": token.intentos_fallidos, "bloqueado": token.bloqueado}, **base_auditoria)
            if token.bloqueado:
                ServicioAuditoria.registrar_evento(db=db, evento="FIRMA_TOKEN_BLOQUEADO", resultado="BLOQUEADO_TRAS_3_INTENTOS",
                                                   entidad_id=str(token.id), datos_nuevos=datos, **base_auditoria)
                raise TokenFirmaBloqueadoError("Token bloqueado tras 3 intentos incorrectos. Genere un token nuevo.")
            restantes = MAX_INTENTOS_TOKEN - token.intentos_fallidos
            raise FirmaInvalidaError(f"Token incorrecto. Le quedan {restantes} intento(s).")

        token.usado = True
        return token

    @staticmethod
    def crear_firma(db: Session, *, entidad: str, entidad_id: str, rol_firma: str, significado: str, firmante: Usuario,
                    token: TokenOTP, hash_datos: str, sesion: Usuario, ip: str) -> FirmaElectronica:
        """Agrega la firma a la sesión de base de datos (la confirma quien llama, junto con el cambio de estado)."""
        firma = FirmaElectronica(
            entidad=entidad, entidad_id=str(entidad_id), rol_firma=rol_firma, significado=significado,
            usuario_id=firmante.id, username=firmante.username, nombre_completo=firmante.nombre_completo,
            firmado_en=datetime.now(timezone.utc), hash_datos=hash_datos, token_id=token.id,
            registrada_por_id=sesion.id, ip_address=ip,
        )
        db.add(firma)
        return firma

    @staticmethod
    def firmas_de(db: Session, entidad: str, entidad_id) -> dict[str, FirmaElectronica]:
        firmas = db.query(FirmaElectronica).filter(FirmaElectronica.entidad == entidad,
                                                   FirmaElectronica.entidad_id == str(entidad_id)).all()
        return {f.rol_firma: f for f in firmas}
