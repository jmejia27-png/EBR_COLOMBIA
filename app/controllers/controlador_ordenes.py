# app/controllers/controlador_ordenes.py
# CU-03 Cargar orden de trabajo + repositorio de órdenes de trabajo.
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.models.modelo_orden_trabajo import OrdenTrabajo
from app.models.modelo_usuario import RolUsuario, Usuario
from app.schemas.esquema_orden_trabajo import (
    IndicadoresOrdenes, OrdenDetalle, OrdenResumen, RespuestaCargaOrdenes, RespuestaDesarrollo,
    RespuestaValidacionArchivo, SolicitudMotivo,
)
from app.services.servicio_carga_ordenes import (
    MAX_BYTES_ARCHIVO, ArchivoInvalidoError, DecisionRequeridaError, MotivoInvalidoError,
    OrdenNoEncontradaError, ServicioCargaOrdenes, TransicionInvalidaError,
)
from app.services.servicio_login_ebr import obtener_db_ebr, obtener_usuario_sesion_ebr

router = APIRouter(prefix="/ebr", tags=["CU-03 Cargar orden de trabajo"])
templates = Jinja2Templates(directory="app/views")


def _ip(request: Request) -> str:
    return request.client.host if request.client else "127.0.0.1"


def obtener_admin_ebr(
    request: Request,
    db: Session = Depends(obtener_db_ebr),
    usuario: Usuario = Depends(obtener_usuario_sesion_ebr),
) -> Usuario:
    """Solo un usuario con sesión EBR vigente y rol ADMIN puede cargar o eliminar órdenes."""
    if usuario.rol != RolUsuario.ADMIN:
        ServicioCargaOrdenes.registrar_acceso_denegado(db, usuario, request.url.path, _ip(request))
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Esta acción solo la puede realizar un usuario ADMIN.")
    return usuario


async def _leer_archivo(archivo: UploadFile) -> bytes:
    contenido = await archivo.read(MAX_BYTES_ARCHIVO + 1)  # no se lee más allá del límite
    await archivo.close()
    return contenido


def _usuario(u: Optional[Usuario]) -> Optional[str]:
    return (u.nombre_completo or u.username) if u else None


def _resumen(o: OrdenTrabajo) -> dict:
    return {
        "id": o.id, "numero_orden": o.numero_orden, "descripcion": o.descripcion, "pt": o.pt,
        "cantidad_pt": o.cantidad_pt, "total_materiales": o.total_materiales, "estado": o.estado,
        "version": o.version, "cargada_por": _usuario(o.cargada_por) or "", "cargada_en": o.cargada_en,
        "eliminada_por": _usuario(o.eliminada_por), "eliminada_en": o.eliminada_en, "motivo_eliminacion": o.motivo_eliminacion,
    }


def _detalle(o: OrdenTrabajo) -> dict:
    return {
        **_resumen(o),
        "creada_por": _usuario(o.creada_por) or "", "creada_en": o.creada_en,
        "motivo_actualizacion": o.motivo_actualizacion,
        "desarrollo_por": _usuario(o.desarrollo_por), "desarrollo_en": o.desarrollo_en,
        "materiales": o.lineas,
    }


def _error_negocio(error: Exception):
    if isinstance(error, OrdenNoEncontradaError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, (TransicionInvalidaError,)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))


# ====================================================================== pantallas HTML
@router.get("/repositorio-ordenes", response_class=HTMLResponse)
async def pantalla_repositorio(request: Request):
    return templates.TemplateResponse(request=request, name="ordenes_ebr.html")


@router.get("/orden-trabajo/{orden_id}", response_class=HTMLResponse)
async def pantalla_detalle_orden(request: Request, orden_id: uuid.UUID):
    return templates.TemplateResponse(request=request, name="orden_detalle_ebr.html", context={"orden_id": str(orden_id)})


@router.get("/orden-trabajo/{orden_id}/desarrollo", response_class=HTMLResponse)
async def pantalla_desarrollo_orden(request: Request, orden_id: uuid.UUID):
    """Punto de entrada de CU-04 (aún no desarrollado)."""
    return templates.TemplateResponse(request=request, name="desarrollo_orden_ebr.html", context={"orden_id": str(orden_id)})


# ====================================================================== indicadores (inicio)
@router.get("/indicadores/ordenes", response_model=IndicadoresOrdenes)
async def indicadores_ordenes(db: Session = Depends(obtener_db_ebr), usuario: Usuario = Depends(obtener_usuario_sesion_ebr)):
    return ServicioCargaOrdenes.indicadores(db)


# ====================================================================== carga (solo ADMIN)
@router.post("/ordenes/validar", response_model=RespuestaValidacionArchivo)
async def validar_archivo(
    request: Request,
    archivo: UploadFile = File(...),
    db: Session = Depends(obtener_db_ebr),
    admin: Usuario = Depends(obtener_admin_ebr),
):
    contenido = await _leer_archivo(archivo)
    res, existentes = ServicioCargaOrdenes.validar_archivo(db, admin, archivo.filename, contenido, _ip(request))
    ordenes = []
    if res.valido:
        for o in res.ordenes:
            existente = existentes.get(o.numero_orden)
            ordenes.append({
                "numero_orden": o.numero_orden, "descripcion": o.descripcion, "pt": o.pt, "cantidad_pt": o.cantidad_pt,
                "total_materiales": len(o.lineas), "advertencias": o.advertencias, "materiales": o.lineas,
                "situacion": ServicioCargaOrdenes.situacion(existente),
                "existente": {"id": existente.id, "estado": existente.estado, "version": existente.version,
                              "cargada_por": _usuario(existente.cargada_por) or "", "cargada_en": existente.cargada_en}
                if existente else None,
            })
    return {"valido": res.valido, "archivo_nombre": res.archivo_nombre, "total_errores": res.total_errores,
            "errores": res.errores, "ordenes": ordenes}


@router.post("/ordenes", response_model=RespuestaCargaOrdenes, status_code=status.HTTP_201_CREATED)
async def cargar_ordenes(
    request: Request,
    archivo: UploadFile = File(...),
    decisiones: str = Form("{}", max_length=200_000),
    db: Session = Depends(obtener_db_ebr),
    admin: Usuario = Depends(obtener_admin_ebr),
):
    try:
        decisiones_dict = json.loads(decisiones or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Las decisiones enviadas no son válidas.")

    contenido = await _leer_archivo(archivo)
    try:
        resultado = ServicioCargaOrdenes.registrar_carga(db, admin, archivo.filename, contenido, decisiones_dict, _ip(request))
    except ArchivoInvalidoError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={
            "mensaje": str(error), "total_errores": error.resultado.total_errores, "errores": error.resultado.errores})
    except DecisionRequeridaError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"mensaje": str(error), "ordenes": error.ordenes})
    except (MotivoInvalidoError, TransicionInvalidaError) as error:
        _error_negocio(error)

    partes = []
    if resultado["cargadas"]:
        partes.append(f"{len(resultado['cargadas'])} orden(es) cargada(s)")
    if resultado["actualizadas"]:
        partes.append(f"{len(resultado['actualizadas'])} orden(es) actualizada(s) a una nueva versión")
    if resultado["omitidas"]:
        partes.append(f"{len(resultado['omitidas'])} orden(es) sin cambios")
    return {
        "mensaje": (", ".join(partes) + ".").capitalize() if partes else "No se registraron cambios.",
        "cargadas": [{"id": o.id, "numero_orden": o.numero_orden, "version": o.version} for o in resultado["cargadas"]],
        "actualizadas": [{"id": o.id, "numero_orden": o.numero_orden, "version": o.version} for o in resultado["actualizadas"]],
        "omitidas": resultado["omitidas"],
    }


# ====================================================================== repositorio (cualquier sesión EBR)
@router.get("/ordenes", response_model=list[OrdenResumen])
async def listar_ordenes(
    estado: Optional[str] = Query(default=None, max_length=20),
    busqueda: Optional[str] = Query(default=None, max_length=60),
    db: Session = Depends(obtener_db_ebr),
    usuario: Usuario = Depends(obtener_usuario_sesion_ebr),
):
    return [_resumen(o) for o in ServicioCargaOrdenes.listar_ordenes(db, estado, busqueda)]


@router.get("/ordenes/{orden_id}", response_model=OrdenDetalle)
async def detalle_orden(orden_id: uuid.UUID, db: Session = Depends(obtener_db_ebr),
                        usuario: Usuario = Depends(obtener_usuario_sesion_ebr)):
    orden = ServicioCargaOrdenes.obtener_orden(db, orden_id)
    if not orden:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La orden no existe.")
    return _detalle(orden)


@router.post("/ordenes/{orden_id}/eliminar", response_model=OrdenDetalle)
async def eliminar_orden(orden_id: uuid.UUID, datos: SolicitudMotivo, request: Request,
                         db: Session = Depends(obtener_db_ebr), admin: Usuario = Depends(obtener_admin_ebr)):
    try:
        ServicioCargaOrdenes.eliminar_orden(db, admin, orden_id, datos.motivo, _ip(request))
    except (OrdenNoEncontradaError, TransicionInvalidaError, MotivoInvalidoError) as error:
        _error_negocio(error)
    return _detalle(ServicioCargaOrdenes.obtener_orden(db, orden_id))


@router.post("/ordenes/{orden_id}/desarrollar", response_model=RespuestaDesarrollo)
async def desarrollar_orden(orden_id: uuid.UUID, request: Request, db: Session = Depends(obtener_db_ebr),
                            usuario: Usuario = Depends(obtener_usuario_sesion_ebr)):
    try:
        orden = ServicioCargaOrdenes.iniciar_desarrollo(db, usuario, orden_id, _ip(request))
    except (OrdenNoEncontradaError, TransicionInvalidaError) as error:
        _error_negocio(error)
    return {"estado": orden.estado, "redireccion": f"/ebr/orden-trabajo/{orden.id}/desarrollo"}
