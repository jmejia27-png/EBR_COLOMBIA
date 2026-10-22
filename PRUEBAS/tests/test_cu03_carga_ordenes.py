# tests/test_cu03_carga_ordenes.py
# Pruebas automáticas de CU-03 Cargar orden de trabajo.
# Usan una base SQLite temporal: NO tocan PostgreSQL ni la base de pruebas.
#
# Ejecutar (desde la carpeta PRUEBAS, con el entorno virtual activado):
#     python -m pytest tests -v
import asyncio
import io
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
os.chdir(RAIZ)  # las plantillas y estilos se buscan en app/

_BD = Path(tempfile.gettempdir()) / f"ebr_cu03_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_BD.as_posix()}"   # load_dotenv no sobrescribe variables ya definidas
os.environ["JWT_SECRET_KEY"] = "clave-solo-para-pruebas-automaticas"

import pytest
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from openpyxl import Workbook

from app.database.base_declarativa import Base
from app.database.conexion_postgres import SessionLocal, engine
import app.models  # noqa: F401
from app.main import app
from app.models.modelo_bitacora_auditoria import AuditTrail
from app.models.modelo_orden_trabajo import EstadoOrden, OrdenTrabajo, VersionOrdenTrabajo
from app.models.modelo_usuario import RolUsuario, Usuario
from app.services.servicio_carga_ordenes import COLUMNAS, ServicioCargaOrdenes
from app.services.servicio_login_ebr import (
    ServicioLoginEBR, bearer_scheme_ebr, obtener_db_ebr, obtener_usuario_sesion_ebr,
)


def _usuario_sesion_sqlite(credenciales: HTTPAuthorizationCredentials = Depends(bearer_scheme_ebr),
                           db=Depends(obtener_db_ebr)):
    """En PostgreSQL el id del token (texto) funciona directo; SQLite exige un uuid.UUID.
    Solo para estas pruebas: misma validación de la dependencia real, convirtiendo el id."""
    import jwt
    from app.core.config_entorno import configuracion
    try:
        payload = jwt.decode(credenciales.credentials, configuracion.JWT_SECRET_KEY, algorithms=[configuracion.JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Sesión inválida")
    usuario = db.query(Usuario).filter(Usuario.id == uuid.UUID(payload["sub"])).first()
    if not usuario or not usuario.activo or payload.get("tipo") != "ebr_session":
        raise HTTPException(status_code=401, detail="Sesión inválida")
    return usuario


app.dependency_overrides[obtener_usuario_sesion_ebr] = _usuario_sesion_sqlite

DATOS = RAIZ / "tests" / "datos"
UNA_ORDEN = (DATOS / "orden_3363742.xlsx").read_bytes()
TRES_ORDENES = (DATOS / "tres_ordenes.xlsx").read_bytes()


# ------------------------------------------------------------ cliente ASGI mínimo (sin dependencias extra)
class Respuesta:
    def __init__(self, status, headers, cuerpo):
        self.status_code, self.headers, self.content = status, headers, cuerpo

    def json(self):
        return json.loads(self.content)


def llamar(metodo, ruta, token=None, json_body=None, archivo=None, campos=None):
    headers, cuerpo = [], b""
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if json_body is not None:
        cuerpo = json.dumps(json_body).encode()
        headers.append((b"content-type", b"application/json"))
    if archivo is not None or campos:
        limite = "----limitepruebas"
        partes = [f'--{limite}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'.encode("utf-8")
                  for n, v in (campos or {}).items()]
        if archivo is not None:
            nombre, contenido = archivo
            partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="archivo"; filename="{nombre}"\r\n'
                          f"Content-Type: application/octet-stream\r\n\r\n".encode() + contenido + b"\r\n")
        partes.append(f"--{limite}--\r\n".encode())
        cuerpo = b"".join(partes)
        headers.append((b"content-type", f"multipart/form-data; boundary={limite}".encode()))
    headers.append((b"content-length", str(len(cuerpo)).encode()))
    ruta_sola, _, consulta = ruta.partition("?")
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": metodo, "scheme": "http",
             "path": ruta_sola, "raw_path": ruta_sola.encode(), "query_string": consulta.encode(), "root_path": "",
             "headers": headers, "client": ("127.0.0.1", 50000), "server": ("testserver", 80)}
    enviado, salida = {"listo": False}, {"status": None, "headers": {}, "cuerpo": b""}

    async def recibir():
        if not enviado["listo"]:
            enviado["listo"] = True
            return {"type": "http.request", "body": cuerpo, "more_body": False}
        return {"type": "http.disconnect"}

    async def enviar(mensaje):
        if mensaje["type"] == "http.response.start":
            salida["status"] = mensaje["status"]
            salida["headers"] = {k.decode().lower(): v.decode() for k, v in mensaje["headers"]}
        elif mensaje["type"] == "http.response.body":
            salida["cuerpo"] += mensaje.get("body", b"")

    asyncio.run(app(scope, recibir, enviar))
    return Respuesta(salida["status"], salida["headers"], salida["cuerpo"])


# ------------------------------------------------------------ utilidades
def crear_excel(filas, encabezado=COLUMNAS, hoja="BOM"):
    libro = Workbook()
    ws = libro.active
    ws.title = hoja
    ws.append(encabezado)
    for fila in filas:
        ws.append(fila)
    buffer = io.BytesIO()
    libro.save(buffer)
    return buffer.getvalue()


def fila(orden=3363742, pt=80822781, desc=" OS 2PACK", cant_pt=2244, mat="ECO0001", desc_mat="STRECH", um="RL", cant=0.094):
    return [orden, pt, desc, cant_pt, mat, desc_mat, um, cant]


def eventos(nombre):
    db = SessionLocal()
    try:
        return db.query(AuditTrail).filter(AuditTrail.evento == nombre).all()
    finally:
        db.close()


def orden_por_numero(numero):
    db = SessionLocal()
    try:
        return db.query(OrdenTrabajo).filter(OrdenTrabajo.numero_orden == numero).order_by(OrdenTrabajo.creada_en).all()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def base_limpia():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def tokens():
    db = SessionLocal()
    try:
        admin = Usuario(username="admin_t", email="a@t.co", nombre_completo="Admin Pruebas", password_hash="x", rol=RolUsuario.ADMIN)
        user = Usuario(username="user_t", email="u@t.co", nombre_completo="User Pruebas", password_hash="x", rol=RolUsuario.USER)
        db.add_all([admin, user])
        db.commit()
        return {"admin": ServicioLoginEBR.emitir_sesion_ebr(admin), "user": ServicioLoginEBR.emitir_sesion_ebr(user)}
    finally:
        db.close()


def cargar(token, contenido=TRES_ORDENES, nombre="ordenes.xlsx", decisiones=None):
    return llamar("POST", "/ebr/ordenes", token=token, archivo=(nombre, contenido),
                  campos={"decisiones": json.dumps(decisiones or {})})


# ------------------------------------------------------------ lectura del archivo y separación de órdenes
def test_archivo_de_una_orden():
    res = ServicioCargaOrdenes.analizar_archivo("orden.xlsx", UNA_ORDEN)
    assert res.valido, res.errores
    assert len(res.ordenes) == 1
    o = res.ordenes[0]
    assert (o.numero_orden, o.pt, o.descripcion, o.cantidad_pt) == ("3363742", "80822781", "OS 2PACK XTREME GEL 80gx6IT", 2244)
    assert len(o.lineas) == 9
    assert o.lineas[0]["material"] == "80777251"                    # código numérico guardado como texto
    assert str(o.lineas[1]["cantidad"]) == "0.094"                  # decimales conservados


def test_archivo_de_tres_ordenes_se_separa_por_columna_a():
    res = ServicioCargaOrdenes.analizar_archivo("tres.xlsx", TRES_ORDENES)
    assert res.valido, res.errores
    assert [(o.numero_orden, len(o.lineas)) for o in res.ordenes] == [("3364022", 11), ("3364037", 8), ("3364063", 6)]
    assert [o.pt for o in res.ordenes] == ["80312190-INK", "80881815-INK", "80871514-R"]


def test_ordenes_intercaladas_se_agrupan():
    contenido = crear_excel([fila(orden=1, mat="A"), fila(orden=2, pt=2, mat="B"), fila(orden=1, mat="C")])
    res = ServicioCargaOrdenes.analizar_archivo("o.xlsx", contenido)
    assert res.valido, res.errores
    assert {o.numero_orden: [l["material"] for l in o.lineas] for o in res.ordenes} == {"1": ["A", "C"], "2": ["B"]}


@pytest.mark.parametrize("nombre,contenido,regla", [
    ("orden.csv", b"a,b", "VAL-01"),
    ("orden.xlsx", b"esto no es un excel", "VAL-01"),
    ("orden.xlsx", b"PK" + b"\0" * 100, "VAL-01"),
    ("orden.xlsx", crear_excel([fila()], hoja="Hoja1"), "VAL-02"),
    ("orden.xlsx", crear_excel([fila()], encabezado=["Orden", "PT", "Descripcion", "Cantidad PT", "Material", "Desc", "UM", "Cantidad"]), "VAL-03"),
    ("orden.xlsx", crear_excel([]), "VAL-05"),
    ("orden.xlsx", crear_excel([fila(orden=None)]), "VAL-06"),
    ("orden.xlsx", crear_excel([fila(), fila(pt=111, mat="ECO0002")]), "VAL-08"),
    ("orden.xlsx", crear_excel([fila(cant_pt=0)]), "VAL-09"),
    ("orden.xlsx", crear_excel([fila(cant_pt=10.5)]), "VAL-09"),
    ("orden.xlsx", crear_excel([fila(mat=None)]), "VAL-10"),
    ("orden.xlsx", crear_excel([fila(um="")]), "VAL-10"),
    ("orden.xlsx", crear_excel([fila(cant=-1)]), "VAL-11"),
    ("orden.xlsx", crear_excel([fila(cant="abc")]), "VAL-11"),
])
def test_reglas_de_validacion(nombre, contenido, regla):
    res = ServicioCargaOrdenes.analizar_archivo(nombre, contenido)
    assert not res.valido
    assert regla in {e["regla"] for e in res.errores}, res.errores


def test_archivo_demasiado_grande():
    res = ServicioCargaOrdenes.analizar_archivo("o.xlsx", b"PK" + b"0" * (10 * 1024 * 1024 + 1))
    assert not res.valido and "tamaño máximo" in res.errores[0]["mensaje"]


def test_filas_vacias_se_ignoran_y_material_repetido_es_advertencia():
    res = ServicioCargaOrdenes.analizar_archivo("o.xlsx", crear_excel([fila(), [None] * 8, fila(cant=1)]))
    assert res.valido
    assert len(res.ordenes[0].lineas) == 2 and res.ordenes[0].advertencias


# ------------------------------------------------------------ permisos
def test_sin_sesion_no_hay_acceso():
    assert llamar("GET", "/ebr/ordenes").status_code in (401, 403)
    assert llamar("POST", "/ebr/ordenes/validar", archivo=("o.xlsx", UNA_ORDEN)).status_code in (401, 403)


def test_user_no_puede_cargar_ni_eliminar_y_queda_auditado(tokens):
    assert llamar("POST", "/ebr/ordenes/validar", token=tokens["user"], archivo=("o.xlsx", UNA_ORDEN)).status_code == 403
    assert cargar(tokens["user"], UNA_ORDEN).status_code == 403
    assert cargar(tokens["admin"], UNA_ORDEN).status_code == 201
    orden_id = orden_por_numero("3363742")[0].id
    r = llamar("POST", f"/ebr/ordenes/{orden_id}/eliminar", token=tokens["user"], json_body={"motivo": "no la quiero"})
    assert r.status_code == 403
    assert len(eventos("ORDEN_ACCESO_DENEGADO")) == 3


def test_user_puede_consultar_y_ver_detalle(tokens):
    cargar(tokens["admin"], UNA_ORDEN)
    listado = llamar("GET", "/ebr/ordenes", token=tokens["user"]).json()
    assert [o["numero_orden"] for o in listado] == ["3363742"]
    detalle = llamar("GET", f"/ebr/ordenes/{listado[0]['id']}", token=tokens["user"]).json()
    assert len(detalle["materiales"]) == 9
    assert set(detalle["materiales"][0]) == {"material", "descripcion_material", "um", "cantidad"}  # sin filas ni archivo


# ------------------------------------------------------------ carga
def test_validar_muestra_las_tres_ordenes_como_nuevas(tokens):
    r = llamar("POST", "/ebr/ordenes/validar", token=tokens["admin"], archivo=("tres.xlsx", TRES_ORDENES))
    v = r.json()
    assert r.status_code == 200 and v["valido"]
    assert [(o["numero_orden"], o["situacion"], o["total_materiales"]) for o in v["ordenes"]] == [
        ("3364022", "NUEVA", 11), ("3364037", "NUEVA", 8), ("3364063", "NUEVA", 6)]
    assert orden_por_numero("3364022") == []  # validar no registra nada


def test_validar_archivo_invalido_queda_auditado(tokens):
    v = llamar("POST", "/ebr/ordenes/validar", token=tokens["admin"], archivo=("x.xlsx", crear_excel([fila(cant_pt=0)]))).json()
    assert not v["valido"] and v["errores"][0]["regla"] == "VAL-09"
    assert len(eventos("CARGA_ORDEN_RECHAZADA")) == 1


def test_carga_de_tres_ordenes(tokens):
    r = cargar(tokens["admin"])
    assert r.status_code == 201, r.content
    assert [o["numero_orden"] for o in r.json()["cargadas"]] == ["3364022", "3364037", "3364063"]
    assert len(eventos("ORDEN_CARGADA")) == 3
    listado = llamar("GET", "/ebr/ordenes", token=tokens["admin"]).json()
    assert {o["numero_orden"]: (o["estado"], o["version"], o["cargada_por"]) for o in listado}["3364037"] == ("CARGADA", 1, "Admin Pruebas")
    assert llamar("GET", "/ebr/indicadores/ordenes", token=tokens["user"]).json() == {
        "total": 3, "cargadas": 3, "en_desarrollo": 0, "eliminadas": 0}


def test_carga_con_errores_no_registra_nada(tokens):
    malo = crear_excel([fila(orden=1), fila(orden=2, mat=None)])
    r = cargar(tokens["admin"], malo)
    assert r.status_code == 422 and r.json()["detail"]["errores"][0]["regla"] == "VAL-10"
    assert orden_por_numero("1") == []


# ------------------------------------------------------------ orden existente: versión 2 con motivo
def test_orden_existente_requiere_decision(tokens):
    cargar(tokens["admin"])
    v = llamar("POST", "/ebr/ordenes/validar", token=tokens["admin"], archivo=("tres.xlsx", TRES_ORDENES)).json()
    assert [o["situacion"] for o in v["ordenes"]] == ["EXISTE"] * 3
    assert v["ordenes"][0]["existente"]["version"] == 1

    r = cargar(tokens["admin"])                                              # sin decisiones
    assert r.status_code == 409 and r.json()["detail"]["ordenes"] == ["3364022", "3364037", "3364063"]

    r = cargar(tokens["admin"], decisiones={"3364022": {"accion": "reemplazar", "motivo": "  "},
                                            "3364037": {"accion": "omitir"}, "3364063": {"accion": "omitir"}})
    assert r.status_code == 422 and "motivo" in r.json()["detail"]


def test_reemplazo_crea_version_2(tokens):
    cargar(tokens["admin"])
    r = cargar(tokens["admin"], decisiones={
        "3364022": {"accion": "reemplazar", "motivo": "LX corrigió las cantidades"},
        "3364037": {"accion": "omitir"}, "3364063": {"accion": "omitir"}})
    assert r.status_code == 201, r.content
    datos = r.json()
    assert [o["numero_orden"] for o in datos["actualizadas"]] == ["3364022"] and datos["actualizadas"][0]["version"] == 2
    assert [o["numero_orden"] for o in datos["omitidas"]] == ["3364037", "3364063"]

    ordenes = orden_por_numero("3364022")
    assert len(ordenes) == 1 and ordenes[0].version == 2 and ordenes[0].motivo_actualizacion == "LX corrigió las cantidades"
    db = SessionLocal()
    versiones = db.query(VersionOrdenTrabajo).all()
    assert len(versiones) == 1 and versiones[0].version == 1 and len(versiones[0].datos["materiales"]) == 11
    db.close()

    auditoria = eventos("ORDEN_ACTUALIZADA")
    assert len(auditoria) == 1
    assert auditoria[0].datos_nuevos["motivo"] == "LX corrigió las cantidades" and auditoria[0].datos_nuevos["version"] == 2
    assert auditoria[0].datos_anteriores["version"] == 1

    detalle = llamar("GET", f"/ebr/ordenes/{ordenes[0].id}", token=tokens["admin"]).json()
    assert detalle["version"] == 2 and detalle["motivo_actualizacion"] == "LX corrigió las cantidades"


# ------------------------------------------------------------ eliminar con motivo
def test_eliminar_orden_con_motivo(tokens):
    cargar(tokens["admin"], UNA_ORDEN)
    orden_id = orden_por_numero("3363742")[0].id
    assert llamar("POST", f"/ebr/ordenes/{orden_id}/eliminar", token=tokens["admin"], json_body={"motivo": ""}).status_code == 422

    r = llamar("POST", f"/ebr/ordenes/{orden_id}/eliminar", token=tokens["admin"], json_body={"motivo": "Orden anulada por el cliente"})
    assert r.status_code == 200 and r.json()["estado"] == "ELIMINADA"
    assert r.json()["motivo_eliminacion"] == "Orden anulada por el cliente"
    assert len(eventos("ORDEN_ELIMINADA")) == 1

    assert llamar("GET", "/ebr/ordenes", token=tokens["admin"]).json() == []           # vigentes
    eliminadas = llamar("GET", "/ebr/ordenes?estado=ELIMINADA", token=tokens["admin"]).json()
    assert len(eliminadas) == 1
    assert eliminadas[0]["motivo_eliminacion"] == "Orden anulada por el cliente"
    assert eliminadas[0]["eliminada_por"] == "Admin Pruebas" and eliminadas[0]["eliminada_en"]
    assert llamar("GET", "/ebr/indicadores/ordenes", token=tokens["admin"]).json()["eliminadas"] == 1

    # La misma orden se puede volver a cargar como una orden nueva
    assert cargar(tokens["admin"], UNA_ORDEN).status_code == 201
    assert [o.estado for o in orden_por_numero("3363742")] == [EstadoOrden.ELIMINADA, EstadoOrden.CARGADA]


# ------------------------------------------------------------ desarrollar
def test_desarrollar_bloquea_actualizar_y_eliminar(tokens):
    cargar(tokens["admin"], UNA_ORDEN)
    orden_id = orden_por_numero("3363742")[0].id

    r = llamar("POST", f"/ebr/ordenes/{orden_id}/desarrollar", token=tokens["user"])        # USER también puede
    assert r.status_code == 200 and r.json() == {"estado": "EN_DESARROLLO", "redireccion": f"/ebr/orden-trabajo/{orden_id}/desarrollo"}
    assert len(eventos("ORDEN_DESARROLLO_INICIADA")) == 1
    assert llamar("POST", f"/ebr/ordenes/{orden_id}/desarrollar", token=tokens["user"]).status_code == 200  # continuar
    assert len(eventos("ORDEN_DESARROLLO_INICIADA")) == 1

    r = llamar("POST", f"/ebr/ordenes/{orden_id}/eliminar", token=tokens["admin"], json_body={"motivo": "ya no va"})
    assert r.status_code == 409

    v = llamar("POST", "/ebr/ordenes/validar", token=tokens["admin"], archivo=("o.xlsx", UNA_ORDEN)).json()
    assert v["ordenes"][0]["situacion"] == "EN_DESARROLLO"
    r = cargar(tokens["admin"], UNA_ORDEN, decisiones={"3363742": {"accion": "reemplazar", "motivo": "intento de cambio"}})
    assert r.status_code == 201 and r.json()["omitidas"][0]["numero_orden"] == "3363742"
    assert orden_por_numero("3363742")[0].version == 1


def test_no_se_desarrolla_una_orden_eliminada(tokens):
    cargar(tokens["admin"], UNA_ORDEN)
    orden_id = orden_por_numero("3363742")[0].id
    llamar("POST", f"/ebr/ordenes/{orden_id}/eliminar", token=tokens["admin"], json_body={"motivo": "duplicada"})
    assert llamar("POST", f"/ebr/ordenes/{orden_id}/desarrollar", token=tokens["admin"]).status_code == 409


# ------------------------------------------------------------ pantallas
@pytest.mark.parametrize("ruta", [
    "/ebr/principal", "/ebr/repositorio-ordenes", f"/ebr/orden-trabajo/{uuid.uuid4()}",
    f"/ebr/orden-trabajo/{uuid.uuid4()}/desarrollo",
])
def test_pantallas_de_la_plataforma(ruta):
    r = llamar("GET", ruta)
    assert r.status_code == 200 and b"estilo_yobel.css" in r.content and b'class="sidebar"' in r.content


@pytest.mark.parametrize("ruta", ["/ebr/login", "/otp/", "/admin/panel"])
def test_pantallas_de_acceso_con_diseno_original(ruta):
    r = llamar("GET", ruta)
    assert r.status_code == 200 and b"#F0DE32" in r.content


def test_estilos_y_cabeceras_de_seguridad():
    r = llamar("GET", "/static/css/estilo_yobel.css")
    assert r.status_code == 200 and b"--azul" in r.content
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"


def test_me_incluye_rol(tokens):
    assert llamar("GET", "/ebr/me", token=tokens["admin"]).json()["rol"] == "admin"
