# app/controllers/controlador_desarrollo.py
# CU-04 Desarrollo de la orden de trabajo · formato 03131 V2 y firma electrónica.
# La pantalla HTML /ebr/orden-trabajo/{id}/desarrollo se sirve desde controlador_ordenes (punto de entrada de CU-03).
import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.models.modelo_formato_ebr import EstadoFormato
from app.models.modelo_orden_trabajo import EstadoOrden
from app.models.modelo_usuario import RolUsuario, Usuario
from app.schemas.esquema_formato_ebr import SolicitudFirmaFormato, SolicitudGuardarFormato
from app.services.servicio_auditoria import ServicioAuditoria
from app.services.servicio_firma_electronica import FirmaInvalidaError, ServicioFirmaElectronica, TokenFirmaBloqueadoError
from app.services.servicio_formato_orden import (
    CODIGO_FORMATO, FIRMAS, MODULO, NOMBRE_FORMATO, ORDEN_FIRMAS, VERSION_FORMATO, ConflictoRevisionError,
    FormatoError, FormatoNoEncontradoError, ServicioFormatoOrden, _decimal_json, a_colombia,
)
from app.services.servicio_login_ebr import obtener_db_ebr, obtener_usuario_sesion_ebr

router = APIRouter(prefix="/ebr", tags=["CU-04 Desarrollo de la orden"])
templates = Jinja2Templates(directory="app/views")


def _ip(request: Request) -> str:
    return request.client.host if request.client else "127.0.0.1"


def _error(error: Exception):
    if isinstance(error, FormatoNoEncontradoError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, ConflictoRevisionError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, TokenFirmaBloqueadoError):
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=str(error))
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))


def _fecha(valor):
    return a_colombia(valor).isoformat() if valor else None


def _vista_json(vista: dict, usuario: Usuario) -> dict:
    orden, doc = vista["orden"], vista["documento"]
    es_admin = usuario.rol == RolUsuario.ADMIN
    firmas = []
    siguiente = None
    for rol in ORDEN_FIRMAS:
        f = vista["firmas"].get(rol)
        if not f and siguiente is None:
            siguiente = rol
        firmas.append({
            "rol_firma": rol, "significado": FIRMAS[rol],
            "firmada": bool(f), "nombre_completo": f.nombre_completo if f else None, "username": f.username if f else None,
            "firmado_en": _fecha(f.firmado_en) if f else None, "hash_datos": f.hash_datos if f else None,
        })
    return {
        "formato": {"codigo": CODIGO_FORMATO, "version": VERSION_FORMATO, "nombre": NOMBRE_FORMATO},
        "orden": {"id": str(orden.id), "numero_orden": orden.numero_orden, "pt": orden.pt, "descripcion": orden.descripcion,
                  "cantidad_pt": orden.cantidad_pt, "estado": orden.estado, "version": orden.version},
        "documento": {
            "existe": doc is not None, "estado": vista["estado"], "revision": doc.revision if doc else None,
            "lote": doc.lote if doc else None, "linea": doc.linea if doc else None,
            "fecha_vencimiento": doc.fecha_vencimiento.isoformat() if doc and doc.fecha_vencimiento else None,
            "fecha_documento": doc.fecha_documento.isoformat() if doc else None,
            "actualizado_por": doc.actualizado_por.nombre_completo if doc else None,
            "actualizado_en": _fecha(doc.actualizado_en) if doc else None,
            "completado_en": _fecha(doc.completado_en) if doc else None,
            "pdf_hash_sha256": doc.pdf_hash_sha256 if doc else None,
        },
        "filas": [{
            "linea_id": f["linea_id"], "descripcion": f["descripcion"], "codigo": f["codigo"], "um": f["um"],
            "cantidad": _decimal_json(f["cantidad"]),
            "exc": _decimal_json(f["exc"]), "dev": _decimal_json(f["dev"]), "rot": _decimal_json(f["rot"]),
            "cons": _decimal_json(f["cons"]), "lotes_materiales": f["lotes_materiales"],
        } for f in vista["filas"]],
        "firmas": firmas,
        "permisos": {
            "editar": vista["editable"],
            "firmar": es_admin and orden.estado == EstadoOrden.EN_DESARROLLO and vista["estado"] != EstadoFormato.COMPLETADO,
            "siguiente_firma": siguiente,
            "descargar_pdf": vista["estado"] == EstadoFormato.COMPLETADO,
        },
    }


# ====================================================================== pantallas HTML
@router.get("/desarrollo-ordenes", response_class=HTMLResponse)
async def pantalla_desarrollo_ordenes(request: Request):
    return templates.TemplateResponse(request=request, name="desarrollo_lista_ebr.html")


# ====================================================================== API
@router.get("/desarrollo/ordenes")
async def listar_en_desarrollo(db: Session = Depends(obtener_db_ebr), usuario: Usuario = Depends(obtener_usuario_sesion_ebr)):
    salida = []
    for item in ServicioFormatoOrden.listar_en_desarrollo(db):
        o, d = item["orden"], item["documento"]
        salida.append({
            "id": str(o.id), "numero_orden": o.numero_orden, "descripcion": o.descripcion, "pt": o.pt,
            "cantidad_pt": o.cantidad_pt, "desarrollo_en": _fecha(o.desarrollo_en),
            "desarrollo_por": o.desarrollo_por.nombre_completo if o.desarrollo_por else None,
            "estado_formato": d.estado if d else "SIN_INICIAR", "lote": d.lote if d else None,
            "actualizado_en": _fecha(d.actualizado_en) if d else None,
        })
    return salida


@router.get("/desarrollo/{orden_id}/formato")
async def obtener_formato(orden_id: uuid.UUID, db: Session = Depends(obtener_db_ebr),
                          usuario: Usuario = Depends(obtener_usuario_sesion_ebr)):
    try:
        vista = ServicioFormatoOrden.vista(db, orden_id)
    except FormatoError as error:
        _error(error)
    if vista["orden"].estado != EstadoOrden.EN_DESARROLLO:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="La orden no está en desarrollo. Ábrala desde el repositorio y seleccione DESARROLLAR ORDEN.")
    return _vista_json(vista, usuario)


@router.put("/desarrollo/{orden_id}/formato")
async def guardar_formato(orden_id: uuid.UUID, datos: SolicitudGuardarFormato, request: Request,
                          db: Session = Depends(obtener_db_ebr), usuario: Usuario = Depends(obtener_usuario_sesion_ebr)):
    """ADMIN y USER pueden guardar la información mientras el formato no tenga firmas."""
    try:
        resultado = ServicioFormatoOrden.guardar(db, usuario, orden_id, datos.como_dict(), datos.revision, _ip(request))
    except FormatoError as error:
        _error(error)
    vista = _vista_json(ServicioFormatoOrden.vista(db, orden_id), usuario)
    vista["mensaje"] = "Cambios guardados." if resultado["cambios"] else "No hay cambios por guardar."
    return vista


@router.post("/desarrollo/{orden_id}/formato/previsualizar")
async def previsualizar_formato(orden_id: uuid.UUID, datos: Optional[SolicitudGuardarFormato] = Body(default=None),
                                db: Session = Depends(obtener_db_ebr), usuario: Usuario = Depends(obtener_usuario_sesion_ebr)):
    try:
        pdf = ServicioFormatoOrden.pdf_para_previsualizar(db, orden_id, datos.como_dict() if datos else None)
    except FormatoError as error:
        _error(error)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": "inline; filename=vista_previa.pdf"})


@router.get("/desarrollo/{orden_id}/formato/pdf")
async def descargar_pdf(orden_id: uuid.UUID, request: Request, db: Session = Depends(obtener_db_ebr),
                        usuario: Usuario = Depends(obtener_usuario_sesion_ebr)):
    try:
        pdf, nombre = ServicioFormatoOrden.pdf_definitivo(db, usuario, orden_id, _ip(request))
    except FormatoError as error:
        _error(error)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@router.get("/firmantes")
async def listar_firmantes(busqueda: Optional[str] = Query(default=None, max_length=60),
                           db: Session = Depends(obtener_db_ebr), usuario: Usuario = Depends(obtener_usuario_sesion_ebr)):
    return [{"id": str(u.id), "username": u.username, "nombre_completo": u.nombre_completo,
             "rol": u.rol.value, "puede_firmar": u.rol == RolUsuario.ADMIN}
            for u in ServicioFirmaElectronica.listar_firmantes(db, busqueda)]


@router.post("/desarrollo/{orden_id}/formato/firmar")
async def firmar_formato(orden_id: uuid.UUID, datos: SolicitudFirmaFormato, request: Request,
                         db: Session = Depends(obtener_db_ebr), usuario: Usuario = Depends(obtener_usuario_sesion_ebr)):
    if usuario.rol != RolUsuario.ADMIN:
        ServicioAuditoria.registrar_evento(
            db=db, usuario_id=usuario.id, evento="FORMATO_ACCESO_DENEGADO", modulo=MODULO, entidad="documentos_formato",
            accion="FIRMAR", resultado="ERROR_ROL_NO_AUTORIZADO", ip_address=_ip(request),
            datos_nuevos={"ruta": request.url.path, "rol": usuario.rol.value})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Solo un usuario ADMIN puede firmar. Un usuario USER solo puede guardar la información.")
    try:
        ServicioFormatoOrden.firmar(db, usuario, orden_id, datos.rol_firma, datos.firmante_id, datos.codigo, datos.revision, _ip(request))
    except (FormatoError, FirmaInvalidaError) as error:
        _error(error)
    vista = _vista_json(ServicioFormatoOrden.vista(db, orden_id), usuario)
    vista["mensaje"] = ("Formato firmado y completado. El PDF quedó almacenado en el sistema."
                        if vista["documento"]["estado"] == EstadoFormato.COMPLETADO
                        else "Firma registrada. Los datos del formato quedaron bloqueados.")
    return vista
