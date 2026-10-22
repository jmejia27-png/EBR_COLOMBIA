import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import string

from app.models.modelo_usuario import Usuario
from app.models.modelo_token_otp import TokenOTP
from app.models.modelo_bitacora_auditoria import AuditTrail
from app.core.seguridad_cifrado import verificar_password
from app.services.servicio_auditoria import ServicioAuditoria

ph = PasswordHasher()  # instancia reutilizable para hashear el OTP

class ServicioGeneradorOTP:

    @staticmethod
    def generar_otp_para_usuario(db: Session, username: str, password: str, ip_address: str = "127.0.0.1"):
        usuario = db.query(Usuario).filter(Usuario.username == username).first()
        if not usuario or not usuario.activo:
            ServicioAuditoria.registrar_evento(
                db=db, usuario_id=usuario.id if usuario else None,
                evento="GENERACION_OTP_FALLIDA", modulo="CU-00", entidad="tokens_otp",
                accion="GENERAR", resultado="ERROR_USUARIO_INVALIDO", ip_address=ip_address
            )
            return {"exito": False, "mensaje": "Credenciales inválidas o usuario inactivo"}

        if not verificar_password(password, usuario.password_hash):
            ServicioAuditoria.registrar_evento(
                db=db, usuario_id=usuario.id, evento="GENERACION_OTP_FALLIDA",
                modulo="CU-00", entidad="tokens_otp", accion="GENERAR",
                resultado="ERROR_PASSWORD_INCORRECTA", ip_address=ip_address
            )
            return {"exito": False, "mensaje": "Credenciales inválidas"}

        if usuario.requiere_cambio_password:                                    # NUEVO
            ServicioAuditoria.registrar_evento(
                db=db, usuario_id=usuario.id, evento="GENERACION_OTP_BLOQUEADA",
                modulo="CU-00", entidad="tokens_otp", accion="GENERAR",
                resultado="REQUIERE_CAMBIO_PASSWORD", ip_address=ip_address
            )
            return {
                "exito": False,
                "mensaje": "Debe establecer una nueva contraseña antes de continuar",
                "requiere_cambio_password": True
            }

        return ServicioGeneradorOTP._generar_y_guardar_otp(db, usuario, ip_address)

    @staticmethod
    def generar_otp_para_usuario_ya_autenticado(db: Session, usuario: Usuario, ip_address: str = "127.0.0.1"):
        """Usado justo después de un cambio de contraseña obligatorio exitoso: las
        credenciales ya se verificaron en ese paso, no se vuelven a pedir aquí."""
        return ServicioGeneradorOTP._generar_y_guardar_otp(db, usuario, ip_address)

    @staticmethod
    def _generar_y_guardar_otp(db: Session, usuario: Usuario, ip_address: str = "127.0.0.1"):
        codigo_otp = ''.join(secrets.choice(string.digits) for _ in range(4))
        codigo_otp_hash = ph.hash(codigo_otp)
        ahora = datetime.now(timezone.utc)
        expira_en = ahora + timedelta(seconds=60)

        nuevo_otp = TokenOTP(
            usuario_id=usuario.id, codigo_hash=codigo_otp_hash,
            creado_en=ahora, expira_en=expira_en, usado=False
        )
        db.add(nuevo_otp)
        db.commit()
        db.refresh(nuevo_otp)

        ServicioAuditoria.registrar_evento(
            db=db, usuario_id=usuario.id, evento="GENERACION_OTP_EXITOSA",
            modulo="CU-00", entidad="tokens_otp", entidad_id=str(nuevo_otp.id),
            accion="GENERAR", resultado="EXITO", ip_address=ip_address
        )
        return {"exito": True, "mensaje": "Token OTP generado con éxito", "codigo_otp": codigo_otp, "expira_en_segundos": 60}