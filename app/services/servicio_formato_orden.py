# app/services/servicio_formato_orden.py
# CU-04 Desarrollo de la orden de trabajo · Formato 03131 V2 "Orden de trabajo".
#
# Columnas que vienen de LX (CU-03) -> solo lectura: descripción y código del material, cantidad.
# Columnas del formato -> editables mientras no exista la primera firma: EXC (excedente), DEV (devuelto),
#   ROT (daño en proceso) y lotes de materiales. CONS (consumido) = ROT + EXC, lo calcula el sistema.
#   En el encabezado: lote, fecha de vencimiento y línea(s) (varias líneas separadas por guion: 1-2-3).
# La fecha del formato se toma automáticamente del primer guardado.
# Firmas: "Digitado por" y "Encargado o Supervisor Global", ambas de usuarios ADMIN con token.
#   Con la primera firma los datos quedan bloqueados; con la segunda el formato queda COMPLETADO,
#   se genera el PDF definitivo y se almacena en la base de datos.
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models.modelo_formato_ebr import DocumentoFormato, EstadoFormato, RegistroLineaFormato
from app.models.modelo_orden_trabajo import EstadoOrden, OrdenTrabajo
from app.models.modelo_usuario import RolUsuario, Usuario
from app.services.pdf_basico import DocumentoPDF, ancho_texto, partir_texto
from app.services.servicio_auditoria import ServicioAuditoria
from app.services.servicio_firma_electronica import FirmaInvalidaError, ServicioFirmaElectronica

MODULO = "CU-04"
ENTIDAD = "documentos_formato"
CODIGO_FORMATO = "03131"
VERSION_FORMATO = "V2"
NOMBRE_FORMATO = "Orden de trabajo"
HORA_COLOMBIA = timezone(timedelta(hours=-5), "COT")   # Colombia no tiene horario de verano

LOTE_MAX = 30
LINEA_MAX = 30
LOTES_MAX = 500
CAMPOS_NUMERICOS = ("exc", "dev", "rot", "cons")
CAMPOS_EDITABLES = ("exc", "dev", "rot")                # CONS no se digita: se calcula
CAMPOS_SOLO_POSITIVOS = ("exc", "dev", "rot", "cons")   # solo valores numéricos mayores o iguales a cero
LINEA_PARTE = re.compile(r"^[A-Za-z0-9]{1,10}$")        # cada línea: letras o números (1, 2, L4...)
NOMBRE_CAMPO = {"exc": "Excedente", "dev": "Devuelto", "rot": "Roto",
                "cons": "Consumido", "lotes_materiales": "Lotes de materiales",
                "lote": "Lote", "fecha_vencimiento": "Fecha de vencimiento", "linea": "Línea"}

FIRMAS = {
    "DIGITADO_POR": "Digitado por",
    "SUPERVISOR": "Encargado o Supervisor Global",
}
ORDEN_FIRMAS = ["DIGITADO_POR", "SUPERVISOR"]


class FormatoError(Exception):
    """Error de negocio del formato (datos inválidos o acción no permitida)."""


class FormatoNoEncontradoError(FormatoError):
    pass


class ConflictoRevisionError(FormatoError):
    """Otro usuario guardó el formato después de que este usuario lo abrió."""


@dataclass
class DatosFormato:
    lote: Optional[str]
    fecha_vencimiento: Optional[date]
    linea: Optional[str]
    registros: dict  # linea_id (str) -> {exc, dev, rot, cons, lotes_materiales}


# ====================================================================== utilidades
def ahora_colombia() -> datetime:
    return datetime.now(HORA_COLOMBIA)


def a_colombia(valor: Optional[datetime]) -> Optional[datetime]:
    if valor is None:
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(HORA_COLOMBIA)


def formato_numero(valor) -> str:
    """Número con separadores colombianos: 5.000 · 0,094 · 1.234,5"""
    if valor is None or valor == "":
        return ""
    d = Decimal(str(valor))
    texto = f"{d:,.6f}".rstrip("0").rstrip(".")
    return texto.replace(",", "§").replace(".", ",").replace("§", ".")


def _texto(valor, maximo: int, campo: str) -> Optional[str]:
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise FormatoError(f"{NOMBRE_CAMPO[campo]}: valor inválido.")
    valor = " ".join(valor.split()) if campo != "lotes_materiales" else valor.strip()
    if len(valor) > maximo:
        raise FormatoError(f"{NOMBRE_CAMPO[campo]}: máximo {maximo} caracteres.")
    return valor or None


def _numero(valor, campo: str, material: str) -> Optional[Decimal]:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if isinstance(valor, bool):
        raise FormatoError(f"Material {material}, {NOMBRE_CAMPO[campo]}: valor inválido.")
    texto = str(valor).strip().replace(" ", "")
    if "," in texto and "." not in texto:
        texto = texto.replace(",", ".")
    try:
        numero = Decimal(texto)
    except InvalidOperation:
        raise FormatoError(f"Material {material}, {NOMBRE_CAMPO[campo]}: «{valor}» no es un número.")
    if not numero.is_finite() or abs(numero) >= Decimal("1e12"):
        raise FormatoError(f"Material {material}, {NOMBRE_CAMPO[campo]}: número fuera de rango.")
    if numero.as_tuple().exponent < -6:
        raise FormatoError(f"Material {material}, {NOMBRE_CAMPO[campo]}: máximo 6 decimales.")
    if campo in CAMPOS_SOLO_POSITIVOS and numero < 0:
        raise FormatoError(f"Material {material}, {NOMBRE_CAMPO[campo]}: no puede ser negativo.")
    return numero


def calcular_consumo(exc: Optional[Decimal], rot: Optional[Decimal]) -> Optional[Decimal]:
    """CONS (consumido) = ROT (daño en proceso) + EXC (excedente). Vacío si no hay ninguno de los dos."""
    if exc is None and rot is None:
        return None
    return (exc or Decimal(0)) + (rot or Decimal(0))


def _lineas(valor) -> Optional[str]:
    """Una o varias líneas separadas por guion: «1-2-3» = 3 líneas trabajando sobre la orden."""
    texto = _texto(valor, LINEA_MAX, "linea")
    if texto is None:
        return None
    partes = [p.strip() for p in texto.split("-")]
    if any(not p for p in partes):
        raise FormatoError("Línea: separe las líneas con un solo guion, sin dejar espacios vacíos (ejemplo: 1-2-3).")
    invalidas = [p for p in partes if not LINEA_PARTE.match(p)]
    if invalidas:
        raise FormatoError(f"Línea: «{invalidas[0]}» no es válida. Use solo letras o números separados por guion (ejemplo: 1-2-3).")
    repetidas = sorted({p for p in partes if partes.count(p) > 1})
    if repetidas:
        raise FormatoError(f"Línea: la línea {repetidas[0]} está repetida.")
    return "-".join(partes)


def cantidad_lineas(valor: Optional[str]) -> int:
    return len(valor.split("-")) if valor else 0


def _fecha(valor) -> Optional[date]:
    if valor in (None, ""):
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        raise FormatoError("Fecha de vencimiento: fecha inválida.")


def _decimal_json(valor):
    return None if valor is None else format(Decimal(valor).normalize(), "f")


# ====================================================================== servicio
class ServicioFormatoOrden:

    # ------------------------------------------------------------------ lectura
    @staticmethod
    def obtener_orden(db: Session, orden_id: uuid.UUID) -> OrdenTrabajo:
        orden = (db.query(OrdenTrabajo).options(joinedload(OrdenTrabajo.lineas))
                 .filter(OrdenTrabajo.id == orden_id).first())
        if not orden:
            raise FormatoNoEncontradoError("La orden no existe.")
        return orden

    @staticmethod
    def obtener_documento(db: Session, orden_id: uuid.UUID) -> Optional[DocumentoFormato]:
        return (db.query(DocumentoFormato)
                .options(joinedload(DocumentoFormato.registros), joinedload(DocumentoFormato.creado_por),
                         joinedload(DocumentoFormato.actualizado_por))
                .filter(DocumentoFormato.orden_id == orden_id, DocumentoFormato.codigo_formato == CODIGO_FORMATO)
                .first())

    @staticmethod
    def vista(db: Session, orden_id: uuid.UUID) -> dict:
        """Todo lo que necesita la pantalla y el PDF: datos de LX + datos del formato + firmas."""
        orden = ServicioFormatoOrden.obtener_orden(db, orden_id)
        doc = ServicioFormatoOrden.obtener_documento(db, orden_id)
        registros = {str(r.linea_id): r for r in (doc.registros if doc else [])}
        firmas = ServicioFirmaElectronica.firmas_de(db, ENTIDAD, doc.id) if doc else {}
        filas = []
        for linea in orden.lineas:
            r = registros.get(str(linea.id))
            filas.append({
                "linea_id": str(linea.id), "posicion": linea.posicion,
                # columnas de LX (solo lectura)
                "descripcion": linea.descripcion_material, "codigo": linea.material, "um": linea.um, "cantidad": linea.cantidad,
                # columnas del formato (editables)
                "exc": r.exc if r else None, "dev": r.dev if r else None, "rot": r.rot if r else None,
                "cons": r.cons if r else None, "lotes_materiales": r.lotes_materiales if r else None,
            })
        estado = doc.estado if doc else EstadoFormato.BORRADOR
        return {
            "orden": orden, "documento": doc, "estado": estado, "filas": filas,
            "firmas": {rol: firmas.get(rol) for rol in ORDEN_FIRMAS},
            "editable": orden.estado == EstadoOrden.EN_DESARROLLO and estado == EstadoFormato.BORRADOR,
        }

    @staticmethod
    def listar_en_desarrollo(db: Session) -> list[dict]:
        ordenes = (db.query(OrdenTrabajo).filter(OrdenTrabajo.estado == EstadoOrden.EN_DESARROLLO)
                   .order_by(OrdenTrabajo.desarrollo_en.desc()).limit(500).all())
        docs = {d.orden_id: d for d in db.query(DocumentoFormato).filter(
            DocumentoFormato.codigo_formato == CODIGO_FORMATO,
            DocumentoFormato.orden_id.in_([o.id for o in ordenes] or [uuid.uuid4()])).all()}
        return [{"orden": o, "documento": docs.get(o.id)} for o in ordenes]

    # ------------------------------------------------------------------ validación de datos
    @staticmethod
    def leer_datos(orden: OrdenTrabajo, datos: dict, fecha_documento: date) -> DatosFormato:
        if not isinstance(datos, dict):
            raise FormatoError("Datos inválidos.")
        lineas = {str(l.id): l for l in orden.lineas}
        lote = _texto(datos.get("lote"), LOTE_MAX, "lote")
        linea = _lineas(datos.get("linea"))
        vencimiento = _fecha(datos.get("fecha_vencimiento"))
        if vencimiento and vencimiento < fecha_documento:
            raise FormatoError("La fecha de vencimiento no puede ser anterior a la fecha del formato.")
        registros = {}
        for item in datos.get("registros") or []:
            if not isinstance(item, dict) or str(item.get("linea_id")) not in lineas:
                raise FormatoError("Uno de los materiales enviados no pertenece a la orden.")
            linea_mat = lineas[str(item["linea_id"])]
            fila = {c: _numero(item.get(c), c, linea_mat.material) for c in CAMPOS_EDITABLES}
            fila["cons"] = calcular_consumo(fila["exc"], fila["rot"])   # lo que envíe el usuario en CONS se ignora
            fila["lotes_materiales"] = _texto(item.get("lotes_materiales"), LOTES_MAX, "lotes_materiales")
            registros[str(linea_mat.id)] = fila
        return DatosFormato(lote, vencimiento, linea, registros)

    @staticmethod
    def _foto(doc: Optional[DocumentoFormato], orden: OrdenTrabajo) -> dict:
        """Valores actuales en forma plana (para comparar y auditar cambios)."""
        foto = {"lote": None, "fecha_vencimiento": None, "linea": None}
        if doc:
            foto.update(lote=doc.lote, linea=doc.linea,
                        fecha_vencimiento=doc.fecha_vencimiento.isoformat() if doc.fecha_vencimiento else None)
        materiales = {str(l.id): l.material for l in orden.lineas}
        for r in (doc.registros if doc else []):
            m = materiales.get(str(r.linea_id), str(r.linea_id))
            for c in CAMPOS_NUMERICOS:
                foto[f"{m}.{c}"] = _decimal_json(getattr(r, c))
            foto[f"{m}.lotes_materiales"] = r.lotes_materiales
        return foto

    # ------------------------------------------------------------------ guardar
    @staticmethod
    def guardar(db: Session, usuario: Usuario, orden_id: uuid.UUID, datos: dict, revision: Optional[int], ip: str) -> dict:
        orden = ServicioFormatoOrden.obtener_orden(db, orden_id)
        if orden.estado != EstadoOrden.EN_DESARROLLO:
            raise FormatoError("La orden no está en desarrollo.")
        doc = ServicioFormatoOrden.obtener_documento(db, orden_id)
        if doc and doc.estado != EstadoFormato.BORRADOR:
            raise FormatoError("El formato ya tiene firmas y no admite cambios.")
        if doc and revision is not None and revision != doc.revision:
            raise ConflictoRevisionError(
                f"{doc.actualizado_por.nombre_completo} guardó cambios en el formato después de que usted lo abrió. "
                "Recargue la página para ver la información actual.")

        fecha_documento = doc.fecha_documento if doc else ahora_colombia().date()
        nuevos = ServicioFormatoOrden.leer_datos(orden, datos, fecha_documento)
        antes = ServicioFormatoOrden._foto(doc, orden)
        nuevo_documento = doc is None
        ahora = datetime.now(timezone.utc)
        if nuevo_documento:
            doc = DocumentoFormato(
                orden_id=orden.id, codigo_formato=CODIGO_FORMATO, version_formato=VERSION_FORMATO,
                estado=EstadoFormato.BORRADOR, version_orden=orden.version, fecha_documento=fecha_documento,
                revision=0, creado_por_id=usuario.id, creado_en=ahora, actualizado_por_id=usuario.id, actualizado_en=ahora,
            )
            db.add(doc)

        doc.lote, doc.fecha_vencimiento, doc.linea = nuevos.lote, nuevos.fecha_vencimiento, nuevos.linea
        existentes = {str(r.linea_id): r for r in doc.registros}
        for linea_id, valores in nuevos.registros.items():
            reg = existentes.get(linea_id)
            if reg is None:
                if not any(v is not None for v in valores.values()):
                    continue
                reg = RegistroLineaFormato(linea_id=uuid.UUID(linea_id))
                doc.registros.append(reg)
            for campo, valor in valores.items():
                setattr(reg, campo, valor)

        db.flush()
        despues = ServicioFormatoOrden._foto(doc, orden)
        cambios = {k for k in set(antes) | set(despues) if antes.get(k) != despues.get(k)}
        if not cambios and not nuevo_documento:
            db.rollback()
            return {"documento": doc, "cambios": 0}

        doc.revision += 1
        doc.actualizado_por_id, doc.actualizado_en = usuario.id, ahora
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise ConflictoRevisionError("Otro usuario creó el formato al mismo tiempo. Recargue la página.")

        ServicioAuditoria.registrar_evento(
            db=db, usuario_id=usuario.id, evento="FORMATO_CREADO" if nuevo_documento else "FORMATO_GUARDADO",
            modulo=MODULO, entidad=ENTIDAD, entidad_id=str(doc.id), accion="GUARDAR", resultado="EXITO", ip_address=ip,
            datos_anteriores={"numero_orden": orden.numero_orden, **{k: antes.get(k) for k in sorted(cambios)}},
            datos_nuevos={"numero_orden": orden.numero_orden, "formato": f"{CODIGO_FORMATO} {VERSION_FORMATO}",
                          "revision": doc.revision, **{k: despues.get(k) for k in sorted(cambios)}},
        )
        return {"documento": doc, "cambios": len(cambios)}

    # ------------------------------------------------------------------ contenido y huella
    @staticmethod
    def contenido_canonico(vista: dict) -> dict:
        orden, doc = vista["orden"], vista["documento"]
        return {
            "formato": f"{CODIGO_FORMATO} {VERSION_FORMATO}",
            "orden": {"numero": orden.numero_orden, "pt": orden.pt, "descripcion": orden.descripcion,
                      "cantidad_pt": orden.cantidad_pt, "version": doc.version_orden if doc else orden.version},
            "encabezado": {"lote": doc.lote if doc else None, "linea": doc.linea if doc else None,
                           "fecha_vencimiento": doc.fecha_vencimiento.isoformat() if doc and doc.fecha_vencimiento else None,
                           "fecha": doc.fecha_documento.isoformat() if doc else None},
            "filas": [{"codigo": f["codigo"], "descripcion": f["descripcion"], "cantidad": _decimal_json(f["cantidad"]),
                       **{c: _decimal_json(f[c]) for c in CAMPOS_NUMERICOS},
                       "lotes_materiales": f["lotes_materiales"]} for f in vista["filas"]],
            "firmas": {rol: {"usuario": f.username, "nombre": f.nombre_completo, "fecha": a_colombia(f.firmado_en).isoformat()}
                       for rol, f in vista["firmas"].items() if f},
        }

    @staticmethod
    def huella(contenido: dict) -> str:
        return hashlib.sha256(json.dumps(contenido, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------ firmar
    @staticmethod
    def firmar(db: Session, sesion: Usuario, orden_id: uuid.UUID, rol_firma: str, firmante_id: uuid.UUID,
               codigo: str, revision: Optional[int], ip: str) -> dict:
        if sesion.rol != RolUsuario.ADMIN:
            raise FormatoError("Solo un usuario ADMIN puede firmar.")
        if rol_firma not in FIRMAS:
            raise FormatoError("Tipo de firma inválido.")
        orden = ServicioFormatoOrden.obtener_orden(db, orden_id)
        if orden.estado != EstadoOrden.EN_DESARROLLO:
            raise FormatoError("La orden no está en desarrollo.")
        doc = ServicioFormatoOrden.obtener_documento(db, orden_id)
        if not doc:
            raise FormatoError("Guarde el formato antes de firmar.")
        if revision is not None and revision != doc.revision:
            raise ConflictoRevisionError("El formato cambió después de que usted lo abrió. Recargue la página antes de firmar.")

        if rol_firma == "DIGITADO_POR":
            if doc.estado != EstadoFormato.BORRADOR:
                raise FormatoError("El formato ya tiene la firma «Digitado por».")
            faltantes = [NOMBRE_CAMPO[c] for c in ("lote", "fecha_vencimiento", "linea") if not getattr(doc, c)]
            if faltantes:
                raise FormatoError("Para firmar complete y guarde: " + ", ".join(faltantes) + ".")
        else:
            if doc.estado == EstadoFormato.BORRADOR:
                raise FormatoError("Primero debe firmar «Digitado por».")
            if doc.estado == EstadoFormato.COMPLETADO:
                raise FormatoError("El formato ya está completo.")

        contexto = {"numero_orden": orden.numero_orden, "formato": f"{CODIGO_FORMATO} {VERSION_FORMATO}", "rol_firma": rol_firma}
        try:
            firmante = ServicioFirmaElectronica.validar_firmante(db, firmante_id)
            token = ServicioFirmaElectronica.validar_token(db, firmante, codigo, contexto, sesion, ip)
        except FirmaInvalidaError as error:
            ServicioAuditoria.registrar_evento(
                db=db, usuario_id=sesion.id, evento="FORMATO_FIRMA_RECHAZADA", modulo=MODULO, entidad=ENTIDAD,
                entidad_id=str(doc.id), accion="FIRMAR", resultado="RECHAZADA", ip_address=ip,
                datos_nuevos={**contexto, "firmante_id": str(firmante_id), "motivo": str(error)})
            raise

        hash_datos = ServicioFormatoOrden.huella(ServicioFormatoOrden.contenido_canonico(ServicioFormatoOrden.vista(db, orden_id)))
        firma = ServicioFirmaElectronica.crear_firma(
            db, entidad=ENTIDAD, entidad_id=str(doc.id), rol_firma=rol_firma, significado=FIRMAS[rol_firma],
            firmante=firmante, token=token, hash_datos=hash_datos, sesion=sesion, ip=ip)
        doc.estado = EstadoFormato.FIRMADO_DIGITADOR if rol_firma == "DIGITADO_POR" else EstadoFormato.COMPLETADO
        doc.revision += 1
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise FormatoError("Esta firma ya fue registrada por otro usuario. Recargue la página.")

        if doc.estado == EstadoFormato.COMPLETADO:
            vista = ServicioFormatoOrden.vista(db, orden_id)
            pdf = ServicioFormatoOrden.generar_pdf(vista, definitivo=True)
            doc.pdf, doc.pdf_hash_sha256 = pdf, hashlib.sha256(pdf).hexdigest()
            doc.pdf_generado_en = doc.completado_en = datetime.now(timezone.utc)
        db.commit()

        ServicioAuditoria.registrar_evento(
            db=db, usuario_id=sesion.id, evento="FORMATO_FIRMADO", modulo=MODULO, entidad=ENTIDAD, entidad_id=str(doc.id),
            accion="FIRMAR", resultado="EXITO", ip_address=ip,
            datos_nuevos={**contexto, "firmante": firmante.username, "nombre_completo": firmante.nombre_completo,
                          "firmado_en": a_colombia(firma.firmado_en).isoformat(), "hash_datos": hash_datos})
        if doc.estado == EstadoFormato.COMPLETADO:
            ServicioAuditoria.registrar_evento(
                db=db, usuario_id=sesion.id, evento="FORMATO_COMPLETADO", modulo=MODULO, entidad=ENTIDAD, entidad_id=str(doc.id),
                accion="COMPLETAR", resultado="EXITO", ip_address=ip,
                datos_nuevos={**contexto, "pdf_hash_sha256": doc.pdf_hash_sha256})
        return {"documento": doc, "firma": firma}

    # ------------------------------------------------------------------ PDF
    @staticmethod
    def pdf_para_previsualizar(db: Session, orden_id: uuid.UUID, datos: Optional[dict]) -> bytes:
        """Si el formato está completo devuelve el PDF almacenado. Si no, genera un borrador con los datos de la
        pantalla (aunque aún no se hayan guardado) para que el usuario vea cómo va quedando."""
        vista = ServicioFormatoOrden.vista(db, orden_id)
        doc = vista["documento"]
        if doc and doc.estado == EstadoFormato.COMPLETADO and doc.pdf:
            return doc.pdf
        if datos is not None and vista["editable"]:
            fecha_doc = doc.fecha_documento if doc else ahora_colombia().date()
            nuevos = ServicioFormatoOrden.leer_datos(vista["orden"], datos, fecha_doc)
            vista["borrador"] = {"lote": nuevos.lote, "linea": nuevos.linea, "fecha_vencimiento": nuevos.fecha_vencimiento}
            for f in vista["filas"]:
                f.update(nuevos.registros.get(f["linea_id"], {}))
        return ServicioFormatoOrden.generar_pdf(vista, definitivo=False)

    @staticmethod
    def pdf_definitivo(db: Session, usuario: Usuario, orden_id: uuid.UUID, ip: str) -> tuple[bytes, str]:
        orden = ServicioFormatoOrden.obtener_orden(db, orden_id)
        doc = ServicioFormatoOrden.obtener_documento(db, orden_id)
        if not doc or doc.estado != EstadoFormato.COMPLETADO or not doc.pdf:
            raise FormatoError("El PDF estará disponible cuando el formato tenga las dos firmas.")
        if hashlib.sha256(doc.pdf).hexdigest() != doc.pdf_hash_sha256:
            raise FormatoError("La huella del PDF almacenado no coincide. Contacte al administrador.")
        ServicioAuditoria.registrar_evento(
            db=db, usuario_id=usuario.id, evento="FORMATO_PDF_DESCARGADO", modulo=MODULO, entidad=ENTIDAD, entidad_id=str(doc.id),
            accion="DESCARGAR", resultado="EXITO", ip_address=ip,
            datos_nuevos={"numero_orden": orden.numero_orden, "formato": f"{CODIGO_FORMATO} {VERSION_FORMATO}"})
        return doc.pdf, f"{CODIGO_FORMATO}_{VERSION_FORMATO}_OT_{orden.numero_orden}.pdf"

    @staticmethod
    def generar_pdf(vista: dict, definitivo: bool) -> bytes:
        orden, doc = vista["orden"], vista["documento"]
        enc = vista.get("borrador") or {
            "lote": doc.lote if doc else None, "linea": doc.linea if doc else None,
            "fecha_vencimiento": doc.fecha_vencimiento if doc else None,
        }
        fecha_doc = doc.fecha_documento if doc else None
        pdf = DocumentoPDF(titulo=f"{CODIGO_FORMATO} {VERSION_FORMATO} Orden de trabajo {orden.numero_orden}", autor="EBR Yobel")
        M, ANCHO_UTIL = 28.0, 792.0 - 56.0
        NEGRO, GRIS, GRIS_CLARO = (0, 0, 0), (0.42, 0.48, 0.53), (0.93, 0.94, 0.95)
        AMARILLO = (0.941, 0.871, 0.196)

        # columnas: (título, ancho, clave, alineación)
        columnas = [
            ("DESCRIPCIÓN DEL PRODUCTO", 176, "descripcion", "izq"), ("CÓDIGO DEL PRODUCTO", 84, "codigo", "izq"),
            ("CANTIDAD", 74, "cantidad", "der"), ("EXCEDENTE", 58, "exc", "der"), ("DEVUELTO", 58, "dev", "der"),
            ("ROTO", 58, "rot", "der"), ("CONSUMIDO", 58, "cons", "der"),
            ("LOTES DE MATERIALES", 170, "lotes_materiales", "izq"),
        ]
        TAM, INTERLINEA, PAD = 7.6, 9.4, 4.0

        def celda(f, clave):
            v = f.get(clave)
            if clave in ("cantidad", *CAMPOS_NUMERICOS):
                return formato_numero(v)
            return v or ""

        def encabezado(p, primera):
            p.rect(M, M - 6, ANCHO_UTIL, 4, relleno=AMARILLO, borde=None)
            # título central: código del producto
            p.texto(M, M + 26, orden.pt, 20, "negrita", alinear="centro", ancho=ANCHO_UTIL)
            p.texto(M, M + 40, orden.descripcion, 9.5, "normal", alinear="centro", ancho=ANCHO_UTIL)
            p.texto(M, M + 53, f"ORDEN DE TRABAJO N.º {orden.numero_orden}  ·  CANTIDAD {formato_numero(orden.cantidad_pt)}",
                    8, "negrita", GRIS, alinear="centro", ancho=ANCHO_UTIL)
            # bloque superior derecho, fuera de la tabla
            x_et, x_val, y = M + ANCHO_UTIL - 205, M + ANCHO_UTIL - 112, M + 4
            datos_der = [("CÓDIGO", f"{CODIGO_FORMATO} {VERSION_FORMATO}"), ("LOTE", enc["lote"] or ""),
                         ("FECHA VENCIMIENTO", enc["fecha_vencimiento"].strftime("%d/%m/%Y") if enc["fecha_vencimiento"] else ""),
                         ("LÍNEA(S)", (f"{enc['linea']}  ({cantidad_lineas(enc['linea'])} línea{'s' if cantidad_lineas(enc['linea']) > 1 else ''})" if enc["linea"] else "")), ("FECHA", fecha_doc.strftime("%d/%m/%Y") if fecha_doc else "")]
            for etiqueta, valor in datos_der:
                y += 11.5
                p.texto(x_et, y, etiqueta + ":", 7.2, "negrita")
                p.texto(x_val, y, valor, 8.2, "normal")
                p.linea(x_val, y + 2.5, M + ANCHO_UTIL, y + 2.5, 0.4, GRIS)
            return M + 72

        def cabecera_tabla(p, y):
            x = M
            titulos = [partir_texto(t, w - 2 * PAD, 6.8, "negrita") for t, w, _, _ in columnas]
            alto = max(22, max(len(t) for t in titulos) * 8 + 8)
            for (titulo, w, _, _), lineas_t in zip(columnas, titulos):
                p.rect(x, y, w, alto, relleno=GRIS_CLARO)
                y0 = y + alto / 2 - (len(lineas_t) - 1) * 4 + 2.4
                for i, l in enumerate(lineas_t):
                    p.texto(x, y0 + i * 8, l, 6.8, "negrita", alinear="centro", ancho=w)
                x += w
            return y + alto

        paginas = []
        p = pdf.nueva_pagina(); paginas.append(p)
        y = cabecera_tabla(p, encabezado(p, True))
        LIMITE = 612 - M - 18
        for f in vista["filas"]:
            textos = [partir_texto(celda(f, clave), w - 2 * PAD, TAM, "normal") for _, w, clave, _ in columnas]
            alto = max(len(t) for t in textos) * INTERLINEA + 2 * PAD - 1
            if y + alto > LIMITE:
                p = pdf.nueva_pagina(); paginas.append(p)
                y = cabecera_tabla(p, encabezado(p, False))
            x = M
            for (titulo, w, clave, alin), lineas_c in zip(columnas, textos):
                p.rect(x, y, w, alto)
                for i, l in enumerate(lineas_c):
                    p.texto(x + PAD, y + PAD + 6.6 + i * INTERLINEA, l, TAM, "normal",
                            alinear="der" if alin == "der" else "izq", ancho=w - 2 * PAD)
                x += w
            y += alto

        # ---------------- firmas (debajo del último registro)
        ALTO_FIRMAS = 92
        if y + 14 + ALTO_FIRMAS > LIMITE:
            p = pdf.nueva_pagina(); paginas.append(p)
            y = encabezado(p, False)
        y += 14
        ancho_caja = (ANCHO_UTIL - 16) / 2
        for i, rol in enumerate(ORDEN_FIRMAS):
            x = M + i * (ancho_caja + 16)
            firma = vista["firmas"].get(rol)
            p.rect(x, y, ancho_caja, ALTO_FIRMAS)
            p.rect(x, y, ancho_caja, 16, relleno=GRIS_CLARO)
            p.texto(x + 8, y + 11, FIRMAS[rol].upper() + "  (FIRMA)", 7.4, "negrita")
            if firma:
                cuando = a_colombia(firma.firmado_en)
                p.texto(x, y + 44, firma.nombre_completo, 17, "cursiva", (0.08, 0.2, 0.42), alinear="centro", ancho=ancho_caja)
                p.linea(x + 24, y + 52, x + ancho_caja - 24, y + 52, 0.6)
                p.texto(x, y + 64, f"{firma.nombre_completo}  ·  usuario {firma.username}", 7.6, "negrita", alinear="centro", ancho=ancho_caja)
                p.texto(x, y + 75, "Firmado electrónicamente el " + cuando.strftime("%d/%m/%Y a las %H:%M:%S") + " (hora Colombia, UTC-5)",
                        7.2, "normal", alinear="centro", ancho=ancho_caja)
                p.texto(x, y + 85, f"Huella de los datos firmados: {firma.hash_datos[:32]}…", 6.2, "normal", GRIS, alinear="centro", ancho=ancho_caja)
            else:
                p.linea(x + 24, y + 52, x + ancho_caja - 24, y + 52, 0.6, GRIS)
                p.texto(x, y + 64, "Pendiente de firma", 8, "normal", GRIS, alinear="centro", ancho=ancho_caja)

        # ---------------- marca de agua y pie de página
        total = len(paginas)
        generado = ahora_colombia().strftime("%d/%m/%Y %H:%M")
        for n, pag in enumerate(paginas, 1):
            if not definitivo:
                pag.texto_rotado(396, 330, "BORRADOR · SIN VALIDEZ", 64, 28, "negrita", (0.9, 0.9, 0.9))
                pag.ops.insert(0, pag.ops.pop())   # la marca de agua va al fondo, debajo de la tabla
            pag.linea(M, 612 - M + 2, M + ANCHO_UTIL, 612 - M + 2, 0.4, GRIS)
            izquierda = f"Formato {CODIGO_FORMATO} {VERSION_FORMATO} · {NOMBRE_FORMATO} · OT {orden.numero_orden}"
            if definitivo:
                izquierda += " · Documento firmado electrónicamente en EBR Yobel"
            else:
                izquierda += f" · Vista previa generada el {generado}"
            pag.texto(M, 612 - M + 12, izquierda, 6.8, "normal", GRIS)
            pag.texto(M, 612 - M + 12, f"Página {n} de {total}", 6.8, "normal", GRIS, alinear="der", ancho=ANCHO_UTIL)
        # las páginas se agregaron en orden; las del encabezado repetido también se cuentan
        return pdf.generar(datetime.now())
