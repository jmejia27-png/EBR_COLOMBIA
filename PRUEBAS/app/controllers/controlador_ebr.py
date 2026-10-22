from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.services.servicio_login_ebr import (
    ServicioLoginEBR, CambioPasswordRequeridoError, CodigoBloqueadoError,
    obtener_db_ebr, obtener_usuario_sesion_ebr
)
from app.services.servicio_auditoria import ServicioAuditoria
from app.schemas.esquema_login_ebr import (
    SolicitudLoginEBR, RespuestaLoginEBR,
    SolicitudCambioPasswordEBR, RespuestaCambioPasswordEBR,
    SolicitudCodigoEBR, RespuestaCodigoEBR
)
from app.core.config_entorno import configuracion
from app.models.modelo_usuario import Usuario

router = APIRouter(prefix="/ebr", tags=["CU-02 Login EBR"])
templates = Jinja2Templates(directory="app/views")


@router.get("/login", response_class=HTMLResponse)
async def mostrar_login_ebr(request: Request):
    return templates.TemplateResponse(request=request, name="login_ebr.html")


@router.get("/principal", response_class=HTMLResponse)
async def mostrar_principal_ebr(request: Request):
    return templates.TemplateResponse(request=request, name="principal_ebr.html")


@router.post("/login", response_model=RespuestaLoginEBR)
async def login_ebr(request: Request, datos: SolicitudLoginEBR, db: Session = Depends(obtener_db_ebr)):
    ip_cliente = request.client.host if request.client else "127.0.0.1"
    try:
        ServicioLoginEBR.validar_credenciales_ebr(db, datos.username, datos.password, ip_cliente)
    except CambioPasswordRequeridoError as error:
        return RespuestaLoginEBR(
            requiere_cambio_password=True, motivo_cambio=error.motivo,
            mensaje="Debe actualizar su contraseña antes de continuar"
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error))

    return RespuestaLoginEBR(mensaje="Credenciales válidas. Ingrese el código de autenticación.")


@router.post("/cambiar-password", response_model=RespuestaCambioPasswordEBR)
async def cambiar_password_ebr(request: Request, datos: SolicitudCambioPasswordEBR, db: Session = Depends(obtener_db_ebr)):
    ip_cliente = request.client.host if request.client else "127.0.0.1"
    try:
        ServicioLoginEBR.cambiar_password_ebr(db, datos.username, datos.password_actual, datos.password_nueva, ip_cliente)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error))

    return RespuestaCambioPasswordEBR(exito=True, mensaje="Contraseña actualizada. Ingrese el código de autenticación.")


@router.post("/validar-codigo", response_model=RespuestaCodigoEBR)
async def validar_codigo_ebr(request: Request, datos: SolicitudCodigoEBR, db: Session = Depends(obtener_db_ebr)):
    ip_cliente = request.client.host if request.client else "127.0.0.1"
    try:
        usuario = ServicioLoginEBR.validar_codigo_autenticacion(db, datos.username, datos.codigo, ip_cliente)
    except CodigoBloqueadoError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error))

    token = ServicioLoginEBR.emitir_sesion_ebr(usuario)
    return RespuestaCodigoEBR(
        exito=True, mensaje="Acceso concedido",
        access_token=token, expira_en_minutos=configuracion.EBR_SESSION_EXPIRACION_MINUTOS
    )


@router.get("/me")
async def obtener_perfil_ebr(usuario: Usuario = Depends(obtener_usuario_sesion_ebr)):
    return {
        "id": str(usuario.id), "username": usuario.username, "nombre_completo": usuario.nombre_completo,
        "rol": usuario.rol.value,  # CU-03: la página usa el rol para mostrar la opción Cargar orden
    }


@router.post("/logout")
async def logout_ebr(
    request: Request, db: Session = Depends(obtener_db_ebr), usuario: Usuario = Depends(obtener_usuario_sesion_ebr)
):
    ip_cliente = request.client.host if request.client else "127.0.0.1"
    ServicioAuditoria.registrar_evento(
        db=db, usuario_id=usuario.id, evento="LOGOUT_EBR", modulo="EBR", entidad="usuarios",
        accion="LOGOUT", resultado="EXITO", ip_address=ip_cliente
    )
    return {"exito": True, "mensaje": "Sesión cerrada"}