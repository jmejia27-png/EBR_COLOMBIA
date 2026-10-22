# app/controllers/controlador_autenticacion.py
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.services.servicio_autenticacion import (
    ServicioAutenticacion, obtener_db, obtener_admin_actual, PasswordTemporalError
)
from app.services.servicio_generador_otp import ServicioGeneradorOTP
from app.schemas.esquema_autenticacion import (
    SolicitudLogin, RespuestaLogin, SolicitudCambioPasswordObligatorio, RespuestaCambioPasswordObligatorio
)
from app.core.config_entorno import configuracion
from app.models.modelo_usuario import Usuario, RolUsuario

router = APIRouter(prefix="/auth", tags=["Autenticación Admin"])


@router.post("/login", response_model=RespuestaLogin)
async def login(request: Request, datos: SolicitudLogin, db: Session = Depends(obtener_db)):
    ip_cliente = request.client.host if request.client else "127.0.0.1"

    try:
        usuario = ServicioAutenticacion.autenticar_admin(
            db=db, username=datos.username, password=datos.password, ip_address=ip_cliente
        )
    except PasswordTemporalError as error:
        return RespuestaLogin(rol=error.usuario.rol.value, requiere_cambio_password=True)

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas o sin permisos de administrador"
        )

    token = ServicioAutenticacion.crear_token_acceso(usuario)
    return RespuestaLogin(
        access_token=token, expira_en_minutos=configuracion.JWT_EXPIRACION_MINUTOS, rol=usuario.rol.value
    )


@router.post("/cambiar-password-obligatorio", response_model=RespuestaCambioPasswordObligatorio)
async def cambiar_password_obligatorio(
    request: Request, datos: SolicitudCambioPasswordObligatorio, db: Session = Depends(obtener_db)
):
    ip_cliente = request.client.host if request.client else "127.0.0.1"
    try:
        usuario = ServicioAutenticacion.cambiar_password_obligatorio(
            db, datos.username, datos.password_actual, datos.password_nueva, ip_cliente
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error))

    if usuario.rol == RolUsuario.ADMIN:
        token = ServicioAutenticacion.crear_token_acceso(usuario)
        return RespuestaCambioPasswordObligatorio(
            exito=True, mensaje="Contraseña actualizada. Acceso concedido.",
            rol=usuario.rol.value, access_token=token,
            expira_en_minutos=configuracion.JWT_EXPIRACION_MINUTOS
        )

    resultado_otp = ServicioGeneradorOTP.generar_otp_para_usuario_ya_autenticado(db, usuario, ip_cliente)
    return RespuestaCambioPasswordObligatorio(
        exito=True, mensaje="Contraseña actualizada. Token generado.",
        rol=usuario.rol.value, codigo_otp=resultado_otp["codigo_otp"],
        expira_en_segundos=resultado_otp["expira_en_segundos"]
    )


@router.get("/me")
async def obtener_perfil_actual(admin_actual: Usuario = Depends(obtener_admin_actual)):
    return {"id": str(admin_actual.id), "username": admin_actual.username, "rol": admin_actual.rol.value}