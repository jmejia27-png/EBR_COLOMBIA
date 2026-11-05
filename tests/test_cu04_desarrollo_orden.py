# tests/test_cu04_desarrollo_orden.py
# Pruebas automáticas de CU-04 Desarrollo de la orden (formato 03131 V2 y firma electrónica).
# Usan la misma base SQLite temporal y el mismo cliente que las pruebas de CU-03.
#
# Ejecutar (desde la carpeta PRUEBAS, con el entorno virtual activado):
#     python -m pytest tests -v
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_cu03_carga_ordenes import (  # noqa: E402  (configura la base temporal y el cliente)
    SessionLocal, Usuario, RolUsuario, ServicioLoginEBR, base_limpia, cargar, crear_excel, eventos, fila, llamar, tokens,
)
import pytest  # noqa: E402

from app.models.modelo_formato_ebr import DocumentoFormato, EstadoFormato, FirmaElectronica  # noqa: E402
from app.models.modelo_orden_trabajo import LineaMaterialOrden, OrdenTrabajo  # noqa: E402
from app.models.modelo_token_otp import TokenOTP  # noqa: E402
from app.services.servicio_generador_otp import ServicioGeneradorOTP  # noqa: E402
from app.services.servicio_formato_orden import HORA_COLOMBIA  # noqa: E402

__all__ = ["base_limpia", "tokens"]   # fixtures reutilizadas de CU-03


# ------------------------------------------------------------ utilidades
def orden_en_desarrollo(token, materiales=3):
    filas = [fila(orden=777, pt="80686405", desc="OB ProHealth 7Ben", cant_pt=5000, mat=f"ECO{i:04d}",
                  desc_mat=f"MATERIAL {i}", um="UN", cant=250 + i) for i in range(materiales)]
    assert cargar(token, crear_excel(filas)).status_code == 201
    db = SessionLocal()
    try:
        orden = db.query(OrdenTrabajo).filter(OrdenTrabajo.numero_orden == "777").one()
        orden_id = str(orden.id)
    finally:
        db.close()
    assert llamar("POST", f"/ebr/ordenes/{orden_id}/desarrollar", token=token).status_code == 200
    return orden_id


def api(orden_id):
    return f"/ebr/desarrollo/{orden_id}/formato"


def datos_validos(vista, **cambios):
    cuerpo = {"revision": vista["documento"]["revision"], "lote": "L2026-01", "fecha_vencimiento": "2028-12-31", "linea": "1-2-3",
              "registros": [{"linea_id": f["linea_id"], "exc": "1.5", "dev": "2", "rot": "0.25", "cons": "999",
                             "lotes_materiales": "Sin novedad"} for f in vista["filas"]]}
    cuerpo.update(cambios)
    return cuerpo


def admin_extra(username="supervisor_t", nombre="Supervisor Global Pruebas"):
    db = SessionLocal()
    try:
        u = Usuario(username=username, email=f"{username}@t.co", nombre_completo=nombre, password_hash="x", rol=RolUsuario.ADMIN)
        db.add(u)
        db.commit()
        return str(u.id)
    finally:
        db.close()


def id_de(username):
    db = SessionLocal()
    try:
        return str(db.query(Usuario).filter(Usuario.username == username).one().id)
    finally:
        db.close()


def token_de(username, vencido=False):
    """Simula el Generador de Tokens (CU-01) para el usuario."""
    db = SessionLocal()
    try:
        u = db.query(Usuario).filter(Usuario.username == username).one()
        codigo = ServicioGeneradorOTP.generar_otp_para_usuario_ya_autenticado(db, u)["codigo_otp"]
        if vencido:
            t = db.query(TokenOTP).filter(TokenOTP.usuario_id == u.id).order_by(TokenOTP.creado_en.desc()).first()
            t.expira_en = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        return codigo
    finally:
        db.close()


def firmar(tok, orden_id, rol, username, codigo=None, revision=None):
    return llamar("POST", f"{api(orden_id)}/firmar", token=tok, json_body={
        "rol_firma": rol, "firmante_id": id_de(username), "codigo": codigo or token_de(username), "revision": revision})


def guardado(tokens, orden_id, quien="user"):
    vista = llamar("GET", api(orden_id), token=tokens[quien]).json()
    r = llamar("PUT", api(orden_id), token=tokens[quien], json_body=datos_validos(vista))
    assert r.status_code == 200, r.content
    return r.json()


# ------------------------------------------------------------ acceso y vista inicial
def test_formato_solo_para_ordenes_en_desarrollo(tokens):
    assert cargar(tokens["admin"], crear_excel([fila(orden=555)])).status_code == 201
    db = SessionLocal()
    orden_id = str(db.query(OrdenTrabajo).filter(OrdenTrabajo.numero_orden == "555").one().id)
    db.close()
    assert llamar("GET", api(orden_id), token=tokens["user"]).status_code == 409
    assert llamar("GET", api(orden_id)).status_code in (401, 403)          # sin sesión


def test_vista_inicial_muestra_datos_de_lx_y_columnas_vacias(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"])
    v = llamar("GET", api(orden_id), token=tokens["user"]).json()
    assert v["formato"] == {"codigo": "03131", "version": "V2", "nombre": "Orden de trabajo"}
    assert v["orden"]["pt"] == "80686405"                                   # título central de la hoja
    assert [(f["codigo"], f["descripcion"], f["cantidad"]) for f in v["filas"]][0] == ("ECO0000", "MATERIAL 0", "250")
    assert all(f[c] is None for f in v["filas"] for c in ("exc", "dev", "rot", "cons", "lotes_materiales"))
    assert v["documento"]["existe"] is False and v["documento"]["fecha_documento"] is None
    assert v["permisos"]["editar"] is True
    assert v["permisos"]["firmar"] is False                                 # USER no firma
    assert llamar("GET", api(orden_id), token=tokens["admin"]).json()["permisos"]["firmar"] is True


# ------------------------------------------------------------ guardar
def test_user_guarda_y_la_fecha_es_la_del_primer_guardado(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"])
    d = guardado(tokens, orden_id)
    assert d["documento"]["existe"] and d["documento"]["revision"] == 1
    assert d["documento"]["fecha_documento"] == datetime.now(HORA_COLOMBIA).date().isoformat()
    assert d["filas"][0]["exc"] == "1.5" and d["filas"][0]["dev"] == "2"
    assert d["filas"][0]["cons"] == "1.75"                                   # CONS = ROT + EXC (el 999 enviado se ignora)
    assert d["documento"]["linea"] == "1-2-3"
    creado = eventos("FORMATO_CREADO")
    assert len(creado) == 1 and creado[0].datos_nuevos["lote"] == "L2026-01"

    # guardar sin cambios no crea revisión ni evento
    r = llamar("PUT", api(orden_id), token=tokens["user"], json_body=datos_validos(d))
    assert r.json()["mensaje"] == "No hay cambios por guardar." and r.json()["documento"]["revision"] == 1

    # un cambio queda auditado con el valor anterior y el nuevo
    cuerpo = datos_validos(d)
    cuerpo["registros"][1]["rot"] = "3,25"
    r = llamar("PUT", api(orden_id), token=tokens["admin"], json_body=cuerpo)
    assert r.status_code == 200 and r.json()["documento"]["revision"] == 2
    ev = eventos("FORMATO_GUARDADO")
    assert len(ev) == 1
    assert ev[0].datos_anteriores["ECO0001.rot"] == "0.25" and ev[0].datos_nuevos["ECO0001.rot"] == "3.25"
    assert "lote" not in ev[0].datos_nuevos                                  # solo lo que cambió
    assert r.json()["documento"]["fecha_documento"] == d["documento"]["fecha_documento"]  # la fecha no cambia


def test_columnas_de_lx_no_se_pueden_modificar(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"])
    v = llamar("GET", api(orden_id), token=tokens["user"]).json()
    cuerpo = datos_validos(v)
    for r in cuerpo["registros"]:
        r.update(descripcion="HACKEADO", codigo="X", cantidad="999")
    assert llamar("PUT", api(orden_id), token=tokens["user"], json_body=cuerpo).status_code == 200
    db = SessionLocal()
    try:
        assert {l.descripcion_material for l in db.query(LineaMaterialOrden).all()} == {"MATERIAL 0", "MATERIAL 1", "MATERIAL 2"}
    finally:
        db.close()
    v2 = llamar("GET", api(orden_id), token=tokens["user"]).json()
    assert [f["cantidad"] for f in v2["filas"]] == ["250", "251", "252"]


@pytest.mark.parametrize("campo,valor,texto", [
    ("exc", "-1", "no puede ser negativo"),
    ("rot", "1.1234567", "máximo 6 decimales"),
    ("dev", "-2", "no puede ser negativo"),
    ("rot", "abc", "no es un número"),
])
def test_validacion_de_celdas(tokens, campo, valor, texto):
    orden_id = orden_en_desarrollo(tokens["admin"])
    v = llamar("GET", api(orden_id), token=tokens["user"]).json()
    cuerpo = datos_validos(v)
    cuerpo["registros"][0][campo] = valor
    r = llamar("PUT", api(orden_id), token=tokens["user"], json_body=cuerpo)
    assert r.status_code == 422 and texto in r.json()["detail"]
    assert "ECO0000" in r.json()["detail"]


def test_validacion_de_encabezado(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"])
    v = llamar("GET", api(orden_id), token=tokens["user"]).json()
    ayer = (datetime.now(HORA_COLOMBIA).date() - timedelta(days=1)).isoformat()
    assert llamar("PUT", api(orden_id), token=tokens["user"], json_body=datos_validos(v, fecha_vencimiento=ayer)).status_code == 422
    assert llamar("PUT", api(orden_id), token=tokens["user"], json_body=datos_validos(v, lote="X" * 31)).status_code == 422
    malo = datos_validos(v)
    malo["registros"][0]["linea_id"] = "00000000-0000-0000-0000-000000000000"
    assert llamar("PUT", api(orden_id), token=tokens["user"], json_body=malo).status_code == 422
    assert eventos("FORMATO_CREADO") == []


def test_dos_usuarios_no_se_sobrescriben(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"])
    d = guardado(tokens, orden_id)                                           # revisión 1
    cambio = datos_validos(d, lote="LOTE-B")
    assert llamar("PUT", api(orden_id), token=tokens["admin"], json_body=cambio).status_code == 200   # revisión 2
    viejo = datos_validos(d, lote="LOTE-C")                                   # sigue con la revisión 1
    r = llamar("PUT", api(orden_id), token=tokens["user"], json_body=viejo)
    assert r.status_code == 409 and "Recargue" in r.json()["detail"]


# ------------------------------------------------------------ firmas
def test_user_no_puede_firmar(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"])
    guardado(tokens, orden_id)
    r = firmar(tokens["user"], orden_id, "DIGITADO_POR", "admin_t")
    assert r.status_code == 403
    assert len(eventos("FORMATO_ACCESO_DENEGADO")) == 1


def test_reglas_previas_a_la_firma(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"])
    r = firmar(tokens["admin"], orden_id, "DIGITADO_POR", "admin_t")
    assert r.status_code == 422 and "Guarde el formato" in r.json()["detail"]
    v = llamar("GET", api(orden_id), token=tokens["user"]).json()
    llamar("PUT", api(orden_id), token=tokens["user"], json_body=datos_validos(v, lote=None))
    r = firmar(tokens["admin"], orden_id, "DIGITADO_POR", "admin_t")
    assert r.status_code == 422 and "Lote" in r.json()["detail"]
    r = firmar(tokens["admin"], orden_id, "SUPERVISOR", "admin_t")
    assert r.status_code == 422 and "Digitado por" in r.json()["detail"]


def test_firmante_debe_ser_admin(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"])
    guardado(tokens, orden_id)
    r = firmar(tokens["admin"], orden_id, "DIGITADO_POR", "user_t")
    assert r.status_code == 422 and "ADMIN" in r.json()["detail"]
    assert len(eventos("FORMATO_FIRMA_RECHAZADA")) == 1


def test_token_incorrecto_tres_veces_se_bloquea(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"])
    guardado(tokens, orden_id)
    correcto = token_de("admin_t")
    incorrecto = "0000" if correcto != "0000" else "1111"
    r1 = firmar(tokens["admin"], orden_id, "DIGITADO_POR", "admin_t", codigo=incorrecto)
    assert r1.status_code == 422 and "2 intento" in r1.json()["detail"]
    firmar(tokens["admin"], orden_id, "DIGITADO_POR", "admin_t", codigo=incorrecto)
    r3 = firmar(tokens["admin"], orden_id, "DIGITADO_POR", "admin_t", codigo=incorrecto)
    assert r3.status_code == 423
    assert len(eventos("FIRMA_TOKEN_BLOQUEADO")) == 1
    r4 = firmar(tokens["admin"], orden_id, "DIGITADO_POR", "admin_t", codigo=correcto)   # el token bloqueado ya no sirve
    assert r4.status_code == 422 and "no tiene un token vigente" in r4.json()["detail"]


def test_token_vencido_no_firma(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"])
    guardado(tokens, orden_id)
    r = firmar(tokens["admin"], orden_id, "DIGITADO_POR", "admin_t", codigo=token_de("admin_t", vencido=True))
    assert r.status_code == 422 and "expiró" in r.json()["detail"]
    assert len(eventos("FIRMA_TOKEN_EXPIRADO")) == 1


def test_token_de_otro_usuario_no_sirve(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"])
    guardado(tokens, orden_id)
    admin_extra()
    codigo_supervisor = token_de("supervisor_t")
    r = firmar(tokens["admin"], orden_id, "DIGITADO_POR", "admin_t", codigo=codigo_supervisor)
    assert r.status_code == 422


def test_flujo_completo_de_firmas_y_pdf(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"])
    d = guardado(tokens, orden_id)
    admin_extra()

    r = firmar(tokens["admin"], orden_id, "DIGITADO_POR", "admin_t", revision=d["documento"]["revision"])
    assert r.status_code == 200, r.content
    v = r.json()
    assert v["documento"]["estado"] == EstadoFormato.FIRMADO_DIGITADOR
    assert v["permisos"]["editar"] is False and v["permisos"]["siguiente_firma"] == "SUPERVISOR"
    f1 = v["firmas"][0]
    assert f1["firmada"] and f1["nombre_completo"] == "Admin Pruebas" and f1["username"] == "admin_t"
    assert f1["firmado_en"].endswith("-05:00")                               # hora de Colombia

    # con la primera firma los datos quedan bloqueados
    r = llamar("PUT", api(orden_id), token=tokens["user"], json_body=datos_validos(v, lote="OTRO"))
    assert r.status_code == 422 and "no admite cambios" in r.json()["detail"]
    assert llamar("GET", f"{api(orden_id)}/pdf", token=tokens["user"]).status_code == 422   # aún no hay PDF

    r = firmar(tokens["admin"], orden_id, "SUPERVISOR", "supervisor_t")
    assert r.status_code == 200, r.content
    v = r.json()
    assert v["documento"]["estado"] == EstadoFormato.COMPLETADO and v["permisos"]["descargar_pdf"]
    assert v["permisos"]["firmar"] is False
    assert v["firmas"][1]["nombre_completo"] == "Supervisor Global Pruebas"
    assert len(eventos("FORMATO_FIRMADO")) == 2 and len(eventos("FORMATO_COMPLETADO")) == 1

    db = SessionLocal()
    try:
        doc = db.query(DocumentoFormato).one()
        pdf_guardado, huella = doc.pdf, doc.pdf_hash_sha256
        assert db.query(FirmaElectronica).count() == 2
        assert db.query(TokenOTP).filter(TokenOTP.usado.is_(True)).count() == 2
    finally:
        db.close()
    assert pdf_guardado.startswith(b"%PDF") and len(huella) == 64

    r = llamar("GET", f"{api(orden_id)}/pdf", token=tokens["user"])           # cualquier usuario puede descargarlo
    assert r.status_code == 200 and r.content == pdf_guardado
    assert r.headers["content-type"] == "application/pdf" and "03131_V2_OT_777.pdf" in r.headers["content-disposition"]
    assert len(eventos("FORMATO_PDF_DESCARGADO")) == 1
    prev = llamar("POST", f"{api(orden_id)}/previsualizar", token=tokens["user"])
    assert prev.content == pdf_guardado                                       # la vista previa muestra el definitivo
    assert firmar(tokens["admin"], orden_id, "SUPERVISOR", "supervisor_t").status_code == 422   # no se firma dos veces


def test_vista_previa_con_datos_sin_guardar(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"], materiales=60)            # varias páginas
    v = llamar("GET", api(orden_id), token=tokens["user"]).json()
    r = llamar("POST", f"{api(orden_id)}/previsualizar", token=tokens["user"], json_body=datos_validos(v))
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert b"/Count 3" in r.content or b"/Count 2" in r.content or b"/Count 4" in r.content
    assert eventos("FORMATO_CREADO") == []                                    # previsualizar no guarda
    r = llamar("POST", f"{api(orden_id)}/previsualizar", token=tokens["user"])   # sin datos: formato vacío
    assert r.status_code == 200


def test_panel_de_firmantes_y_listado_en_desarrollo(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"])
    lista = llamar("GET", "/ebr/firmantes", token=tokens["user"]).json()
    assert {(u["username"], u["puede_firmar"]) for u in lista} == {("admin_t", True), ("user_t", False)}
    assert [u["username"] for u in llamar("GET", "/ebr/firmantes?busqueda=admin", token=tokens["user"]).json()] == ["admin_t"]
    filas = llamar("GET", "/ebr/desarrollo/ordenes", token=tokens["user"]).json()
    assert [(f["numero_orden"], f["estado_formato"]) for f in filas] == [("777", "SIN_INICIAR")]
    guardado(tokens, orden_id)
    assert llamar("GET", "/ebr/desarrollo/ordenes", token=tokens["user"]).json()[0]["estado_formato"] == "BORRADOR"


def test_pantallas_html(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"])
    assert llamar("GET", "/ebr/desarrollo-ordenes").status_code == 200
    r = llamar("GET", f"/ebr/orden-trabajo/{orden_id}/desarrollo")
    assert r.status_code == 200 and b"PREVISUALIZAR" in r.content


# ------------------------------------------------------------ ajustes: líneas múltiples y consumo automático
@pytest.mark.parametrize("valor,esperado", [
    ("1-2-3", "1-2-3"), (" 1 - 2 ", "1-2"), ("4", "4"), ("L1-L2", "L1-L2"),
    ("1--2", None), ("1-2-", None), ("1-1", None), ("1/2", None),
])
def test_varias_lineas_separadas_por_guion(tokens, valor, esperado):
    orden_id = orden_en_desarrollo(tokens["admin"])
    v = llamar("GET", api(orden_id), token=tokens["user"]).json()
    r = llamar("PUT", api(orden_id), token=tokens["user"], json_body=datos_validos(v, linea=valor))
    if esperado is None:
        assert r.status_code == 422 and "Línea" in r.json()["detail"]
    else:
        assert r.status_code == 200, r.content
        assert r.json()["documento"]["linea"] == esperado


def test_consumo_se_calcula_rot_mas_exc(tokens):
    orden_id = orden_en_desarrollo(tokens["admin"])
    v = llamar("GET", api(orden_id), token=tokens["user"]).json()
    cuerpo = datos_validos(v)
    cuerpo["registros"][0].update(exc="10", rot="2,5", cons="1")       # solo EXC y ROT cuentan
    cuerpo["registros"][1].update(exc=None, rot="3", cons=None)        # sin excedente: CONS = ROT
    cuerpo["registros"][2].update(exc=None, rot=None, dev="4", cons="7")  # sin EXC ni ROT: CONS vacío
    r = llamar("PUT", api(orden_id), token=tokens["user"], json_body=cuerpo)
    assert r.status_code == 200, r.content
    assert [f["cons"] for f in r.json()["filas"]] == ["12.5", "3", None]
