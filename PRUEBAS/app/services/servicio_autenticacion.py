# app/services/servicio_autenticacion.py
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.config_entorno import configuracion
from app.core.seguridad_cifrado import verificar_password, obtener_password_hash
from app.database.conexion_postgres import SessionLocal
from app.models.modelo_usuario import Usuario, RolUsuario
from app.services.servicio_auditoria import ServicioAuditoria

bearer_scheme = HTTPBearer()


class PasswordTemporalError(Exception):
    """Se lanza cuando las credenciales de un ADMIN son válidas pero la cuenta
    tiene una contraseña temporal pendiente de cambio. Solo aplica a admins:
    un usuario con rol 'user' nunca llega a esta validación, porque el chequeo
    de rol ocurre primero."""
    def __init__(self, usuario: Usuario):
        self.usuario = usuario
        super().__init__("La contraseña es temporal y debe cambiarse antes de continuar")


def obtener_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ServicioAutenticacion:

    @staticmethod
    def autenticar_admin(db: Session, username: str, password: str, ip_address: str = "127.0.0.1"):
        usuario = db.query(Usuario).filter(Usuario.username == username).first()

        if not usuario or not usuario.activo:
            ServicioAuditoria.registrar_evento(
                db=db, usuario_id=usuario.id if usuario else None,
                evento="LOGIN_ADMIN_FALLIDO", modulo="ADMIN", entidad="usuarios",
                accion="LOGIN", resultado="ERROR_USUARIO_INVALIDO", ip_address=ip_address,
                datos_nuevos={"username_intentado": username} if not usuario else None
            )
            return None

        if not verificar_password(password, usuario.password_hash):
            ServicioAuditoria.registrar_evento(
                db=db, usuario_id=usuario.id, evento="LOGIN_ADMIN_FALLIDO",
                modulo="ADMIN", entidad="usuarios", accion="LOGIN",
                resultado="ERROR_PASSWORD_INCORRECTA", ip_address=ip_address
            )
            return None

        if usuario.rol != RolUsuario.ADMIN:                                     # MOVIDO: ahora se valida primero
            ServicioAuditoria.registrar_evento(
                db=db, usuario_id=usuario.id, evento="LOGIN_ADMIN_FALLIDO",
                modulo="ADMIN", entidad="usuarios", accion="LOGIN",
                resultado="ERROR_ROL_INSUFICIENTE", ip_address=ip_address
            )
            return None

        if usuario.requiere_cambio_password:                                    # MOVIDO: ahora se valida después
            ServicioAuditoria.registrar_evento(
                db=db, usuario_id=usuario.id, evento="LOGIN_ADMIN_PASSWORD_TEMPORAL",
                modulo="ADMIN", entidad="usuarios", accion="LOGIN",
                resultado="REQUIERE_CAMBIO_PASSWORD", ip_address=ip_address
            )
            raise PasswordTemporalError(usuario)

        ServicioAuditoria.registrar_evento(
            db=db, usuario_id=usuario.id, evento="LOGIN_ADMIN_EXITOSO",
            modulo="ADMIN", entidad="usuarios", accion="LOGIN",
            resultado="EXITO", ip_address=ip_address
        )
        return usuario

    @staticmethod
    def crear_token_acceso(usuario: Usuario) -> str:
        ahora = datetime.now(timezone.utc)
        expira = ahora + timedelta(minutes=configuracion.JWT_EXPIRACION_MINUTOS)
        payload = {
            "sub": str(usuario.id), "username": usuario.username,
            "rol": usuario.rol.value, "iat": ahora, "exp": expira
        }
        return jwt.encode(payload, configuracion.JWT_SECRET_KEY, algorithm=configuracion.JWT_ALGORITHM)

    @staticmethod
    def cambiar_password_obligatorio(
        db: Session, username: str, password_actual: str, password_nueva: str,
        ip_address: str = "127.0.0.1"
    ) -> Usuario:
        usuario = db.query(Usuario).filter(Usuario.username == username).first()
        if not usuario or not usuario.activo:
            raise ValueError("Usuario inválido o inactivo")

        if not usuario.requiere_cambio_password:
            raise ValueError("Este usuario no tiene pendiente un cambio obligatorio de contraseña")

        if not verificar_password(password_actual, usuario.password_hash):
            ServicioAuditoria.registrar_evento(
                db=db, usuario_id=usuario.id, evento="CAMBIO_PASSWORD_OBLIGATORIO_FALLIDO",
                modulo="AUTH", entidad="usuarios", accion="CAMBIAR_PASSWORD",
                resultado="ERROR_PASSWORD_ACTUAL_INCORRECTA", ip_address=ip_address
            )
            raise ValueError("La contraseña actual no es correcta")

        usuario.password_hash = obtener_password_hash(password_nueva)
        usuario.requiere_cambio_password = False
        db.commit()
        db.refresh(usuario)

        ServicioAuditoria.registrar_evento(
            db=db, usuario_id=usuario.id, evento="CAMBIO_PASSWORD_OBLIGATORIO_EXITOSO",
            modulo="AUTH", entidad="usuarios", accion="CAMBIAR_PASSWORD",
            resultado="EXITO", ip_address=ip_address
        )
        return usuario


def obtener_admin_actual(
    credenciales: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(obtener_db)
) -> Usuario:
    """
    Dependency que se usará en TODOS los endpoints del CRUD de usuarios
    y del visor de auditoría. Rechaza si el token es inválido, expiró,
    o el usuario ya no tiene rol admin / fue desactivado.
    """
    token = credenciales.credentials
    credenciales_invalidas = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudo validar la credencial",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            configuracion.JWT_SECRET_KEY,
            algorithms=[configuracion.JWT_ALGORITHM]
        )
        usuario_id = payload.get("sub")
        rol = payload.get("rol")
        if usuario_id is None or rol != RolUsuario.ADMIN.value:
            raise credenciales_invalidas
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sesión ha expirado, inicie sesión nuevamente"
        )
    except jwt.InvalidTokenError:
        raise credenciales_invalidas

    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario or not usuario.activo or usuario.rol != RolUsuario.ADMIN:
        raise credenciales_invalidas

    return usuario