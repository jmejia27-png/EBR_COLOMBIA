from datetime import datetime, timedelta, timezone
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config_entorno import configuracion
from app.core.seguridad_cifrado import obtener_password_hash, verificar_password
from app.database.conexion_postgres import SessionLocal
from app.models.modelo_token_otp import TokenOTP
from app.models.modelo_usuario import Usuario
from app.services.servicio_auditoria import ServicioAuditoria

bearer_scheme_ebr = HTTPBearer()

ph = PasswordHasher()
DIAS_VIGENCIA_PASSWORD = 30


class CambioPasswordRequeridoError(Exception):
    def __init__(self, usuario: Usuario, motivo: str):
        self.usuario = usuario
        self.motivo = motivo
        super().__init__("La contraseña debe actualizarse antes de continuar")


class CodigoBloqueadoError(Exception):
    pass


class ServicioLoginEBR:

    @staticmethod
    def validar_credenciales_ebr(
        db: Session,
        username: str,
        password: str,
        ip_address: str = "127.0.0.1",
    ) -> Usuario:
        usuario = (
            db.query(Usuario).filter(Usuario.username == username).first()
        )

        if not usuario or not usuario.activo:
            ServicioAuditoria.registrar_evento(
                db=db,
                usuario_id=usuario.id if usuario else None,
                evento="LOGIN_EBR_FALLIDO",
                modulo="EBR",
                entidad="usuarios",
                accion="LOGIN",
                resultado="ERROR_USUARIO_INVALIDO",
                ip_address=ip_address,
                datos_nuevos={"username_intentado": username}
                if not usuario
                else None,
            )
            raise ValueError("Credenciales inválidas o usuario inhabilitado")

        if not verificar_password(password, usuario.password_hash):
            ServicioAuditoria.registrar_evento(
                db=db,
                usuario_id=usuario.id,
                evento="LOGIN_EBR_FALLIDO",
                modulo="EBR",
                entidad="usuarios",
                accion="LOGIN",
                resultado="ERROR_PASSWORD_INCORRECTA",
                ip_address=ip_address,
            )
            raise ValueError("Credenciales inválidas")

        if usuario.requiere_cambio_password:
            ServicioAuditoria.registrar_evento(
                db=db,
                usuario_id=usuario.id,
                evento="LOGIN_EBR_REQUIERE_CAMBIO",
                modulo="EBR",
                entidad="usuarios",
                accion="LOGIN",
                resultado="PRIMER_INGRESO_O_RESTABLECIMIENTO",
                ip_address=ip_address,
            )
            raise CambioPasswordRequeridoError(
                usuario, "PRIMER_INGRESO_O_RESTABLECIMIENTO"
            )

        fecha_cambio = getattr(
            usuario,
            "password_actualizada_en",
            getattr(usuario, "fecha_ultimo_cambio_password", None),
        )
        if fecha_cambio:
            if fecha_cambio.tzinfo is None:
                fecha_cambio = fecha_cambio.replace(tzinfo=timezone.utc)
            dias_transcurridos = (
                datetime.now(timezone.utc) - fecha_cambio
            ).days
            if dias_transcurridos >= DIAS_VIGENCIA_PASSWORD:
                ServicioAuditoria.registrar_evento(
                    db=db,
                    usuario_id=usuario.id,
                    evento="LOGIN_EBR_REQUIERE_CAMBIO",
                    modulo="EBR",
                    entidad="usuarios",
                    accion="LOGIN",
                    resultado="VENCIMIENTO_30_DIAS",
                    ip_address=ip_address,
                )
                raise CambioPasswordRequeridoError(
                    usuario, "VENCIMIENTO_30_DIAS"
                )

        ServicioAuditoria.registrar_evento(
            db=db,
            usuario_id=usuario.id,
            evento="LOGIN_EBR_CREDENCIALES_VALIDAS",
            modulo="EBR",
            entidad="usuarios",
            accion="LOGIN",
            resultado="EXITO",
            ip_address=ip_address,
        )
        return usuario

    @staticmethod
    def cambiar_password_ebr(
        db: Session,
        username: str,
        password_actual: str,
        password_nueva: str,
        ip_address: str = "127.0.0.1",
    ) -> Usuario:
        usuario = (
            db.query(Usuario).filter(Usuario.username == username).first()
        )
        if not usuario or not usuario.activo:
            raise ValueError("Usuario inválido o inactivo")

        if not verificar_password(password_actual, usuario.password_hash):
            ServicioAuditoria.registrar_evento(
                db=db,
                usuario_id=usuario.id,
                evento="CAMBIO_PASSWORD_EBR_FALLIDO",
                modulo="EBR",
                entidad="usuarios",
                accion="CAMBIAR_PASSWORD",
                resultado="ERROR_PASSWORD_ACTUAL_INCORRECTA",
                ip_address=ip_address,
            )
            raise ValueError("La contraseña actual no es correcta")

        usuario.password_hash = obtener_password_hash(password_nueva)
        ahora = datetime.now(timezone.utc)

        if hasattr(usuario, "password_actualizada_en"):
            usuario.password_actualizada_en = ahora
        if hasattr(usuario, "fecha_ultimo_cambio_password"):
            usuario.fecha_ultimo_cambio_password = ahora

        usuario.requiere_cambio_password = False
        db.commit()
        db.refresh(usuario)

        ServicioAuditoria.registrar_evento(
            db=db,
            usuario_id=usuario.id,
            evento="CAMBIO_PASSWORD_EBR_EXITOSO",
            modulo="EBR",
            entidad="usuarios",
            accion="CAMBIAR_PASSWORD",
            resultado="EXITO",
            ip_address=ip_address,
        )
        return usuario

    @staticmethod
    def validar_codigo_autenticacion(
        db: Session, username: str, codigo: str, ip_address: str = "127.0.0.1"
    ) -> Usuario:
        usuario = (
            db.query(Usuario).filter(Usuario.username == username).first()
        )
        if not usuario or not usuario.activo:
            raise ValueError("Usuario inválido o inactivo")

        token = (
            db.query(TokenOTP)
            .filter(
                TokenOTP.usuario_id == usuario.id,
                TokenOTP.usado == False,
                TokenOTP.bloqueado == False,
            )
            .order_by(TokenOTP.creado_en.desc())
            .first()
        )

        if not token:
            ServicioAuditoria.registrar_evento(
                db=db,
                usuario_id=usuario.id,
                evento="CODIGO_EBR_NO_ENCONTRADO",
                modulo="EBR",
                entidad="tokens_otp",
                accion="VALIDAR_CODIGO",
                resultado="ERROR_SIN_CODIGO_VIGENTE",
                ip_address=ip_address,
            )
            raise ValueError(
                "No hay un código vigente. Genere uno nuevo desde la aplicación de tokens."
            )

        ahora = datetime.now(timezone.utc)
        expira_en = (
            token.expira_en
            if token.expira_en.tzinfo
            else token.expira_en.replace(tzinfo=timezone.utc)
        )

        if ahora > expira_en:
            ServicioAuditoria.registrar_evento(
                db=db,
                usuario_id=usuario.id,
                evento="CODIGO_EBR_EXPIRADO",
                modulo="EBR",
                entidad="tokens_otp",
                entidad_id=str(token.id),
                accion="VALIDAR_CODIGO",
                resultado="ERROR_CODIGO_EXPIRADO",
                ip_address=ip_address,
            )
            raise ValueError("El código ha expirado. Genere uno nuevo.")

        try:
            codigo_hash = getattr(token, "codigo_hash", None)
            if codigo_hash:
                ph.verify(codigo_hash, codigo)
            elif hasattr(token, "codigo_otp"):
                if token.codigo_otp != codigo:
                    raise VerifyMismatchError()
            else:
                raise VerifyMismatchError()
        except VerifyMismatchError:
            intentos = getattr(token, "intentos_fallidos", 0) + 1
            token.intentos_fallidos = intentos
            bloqueado_ahora = intentos >= 3
            token.bloqueado = bloqueado_ahora
            db.commit()

            ServicioAuditoria.registrar_evento(
                db=db,
                usuario_id=usuario.id,
                evento="CODIGO_EBR_INCORRECTO",
                modulo="EBR",
                entidad="tokens_otp",
                entidad_id=str(token.id),
                accion="VALIDAR_CODIGO",
                resultado="ERROR_CODIGO_INCORRECTO",
                ip_address=ip_address,
                datos_nuevos={
                    "intentos_fallidos": intentos,
                    "bloqueado": bloqueado_ahora,
                },
            )

            if bloqueado_ahora:
                ServicioAuditoria.registrar_evento(
                    db=db,
                    usuario_id=usuario.id,
                    evento="CODIGO_EBR_BLOQUEADO",
                    modulo="EBR",
                    entidad="tokens_otp",
                    entidad_id=str(token.id),
                    accion="VALIDAR_CODIGO",
                    resultado="BLOQUEADO_TRAS_3_INTENTOS",
                    ip_address=ip_address,
                )
                raise CodigoBloqueadoError(
                    "Código bloqueado tras 3 intentos incorrectos. Genere uno nuevo."
                )

            raise ValueError("Código incorrecto")

        token.usado = True
        db.commit()

        ServicioAuditoria.registrar_evento(
            db=db,
            usuario_id=usuario.id,
            evento="LOGIN_EBR_EXITOSO",
            modulo="EBR",
            entidad="tokens_otp",
            entidad_id=str(token.id),
            accion="LOGIN",
            resultado="EXITO",
            ip_address=ip_address,
        )
        return usuario

    @staticmethod
    def emitir_sesion_ebr(usuario: Usuario) -> str:
        ahora = datetime.now(timezone.utc)
        expira = ahora + timedelta(
            minutes=configuracion.EBR_SESSION_EXPIRACION_MINUTOS
        )
        payload = {
            "sub": str(usuario.id),
            "username": usuario.username,
            "tipo": "ebr_session",
            "iat": ahora,
            "exp": expira,
        }
        return jwt.encode(
            payload,
            configuracion.JWT_SECRET_KEY,
            algorithm=configuracion.JWT_ALGORITHM,
        )


def obtener_db_ebr():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def obtener_usuario_sesion_ebr(
    credenciales: HTTPAuthorizationCredentials = Depends(bearer_scheme_ebr),
    db: Session = Depends(obtener_db_ebr),
) -> Usuario:
    credenciales_invalidas = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sesión inválida, inicie sesión nuevamente",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            credenciales.credentials,
            configuracion.JWT_SECRET_KEY,
            algorithms=[configuracion.JWT_ALGORITHM],
        )
        if payload.get("tipo") != "ebr_session" or not payload.get("sub"):
            raise credenciales_invalidas
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sesión ha expirado, inicie sesión nuevamente",
        )
    except jwt.InvalidTokenError:
        raise credenciales_invalidas

    usuario = db.query(Usuario).filter(Usuario.id == payload["sub"]).first()
    if not usuario or not usuario.activo:
        raise credenciales_invalidas
    return usuario