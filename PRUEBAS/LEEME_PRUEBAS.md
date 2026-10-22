# PRUEBAS — EBR_COLOMBIA

Copia del proyecto tomada el 20-oct-2026 para probar casos de uso antes de pasarlos a la carpeta principal.
Contiene CU-00, CU-01 y CU-02 tal como estaban, más **CU-03 Cargar orden de trabajo**.

Diferencias con la carpeta principal:

- `.env` apunta a la base **ebr_pruebas_db** (la principal sigue en ebr_demo_db).
- Tiene su propio entorno virtual `.venv` y un `requirements.txt` con versiones fijas.
- Las tablas se crean con `scripts\preparar_bd_pruebas.py` (las migraciones de Alembic siguen desactualizadas).

## 1. Preparar el entorno (una sola vez)

En PowerShell, dentro de `C:\EBR_COLOMBIA\PRUEBAS`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts\preparar_bd_pruebas.py
```

El último comando crea la base `ebr_pruebas_db` (si no existe), todas las tablas y dos usuarios.
Le pedirá la contraseña de cada uno:

| Usuario | Rol | Uso |
| --- | --- | --- |
| admin_pruebas | ADMIN | Puede cargar órdenes |
| usuario_pruebas | USER | Solo consulta el repositorio |

Si PowerShell bloquea `Activate.ps1`, ejecute antes:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## 2. Pruebas automáticas

```powershell
python -m pytest tests -v
```

Resultado esperado: **28 passed**. Usan una base SQLite temporal y no tocan PostgreSQL.

## 3. Levantar el servidor de pruebas

```powershell
uvicorn app.main:app --reload --port 8001
```

Se usa el puerto 8001 para poder tener la versión principal en el 8000 al mismo tiempo.

- Generador de tokens: http://127.0.0.1:8001/otp/
- Login EBR: http://127.0.0.1:8001/ebr/login
- Repositorio de órdenes: http://127.0.0.1:8001/ebr/repositorio-ordenes

## 4. Escenarios de prueba manual de CU-03

Archivos de ejemplo en `tests\datos\`: `orden_3363742.xlsx` (válido) y `tres_ordenes.xlsx` (inválido).

| # | Pasos | Resultado esperado |
| --- | --- | --- |
| P1 | Generar código en /otp/ con admin_pruebas, entrar por /ebr/login y pulsar REPOSITORIO DE ÓRDENES DE TRABAJO | Se ve el repositorio vacío y el botón + CARGAR ORDEN |
| P2 | Repetir P1 con usuario_pruebas | Se ve el repositorio, pero NO el botón + CARGAR ORDEN |
| P3 | Con admin: + CARGAR ORDEN, elegir `tres_ordenes.xlsx`, VALIDAR ARCHIVO | Error VAL-07: "El archivo contiene 3 órdenes… Cargue un archivo por orden." No se registra nada |
| P4 | Elegir cualquier archivo que no sea Excel (renómbrelo a .xlsx si hace falta) | Error VAL-01 |
| P5 | Elegir `orden_3363742.xlsx`, VALIDAR ARCHIVO | Vista previa: orden 3363742, PT 80822781, cantidad 2.244, 9 materiales |
| P6 | En la vista previa pulsar CANCELAR | Se cierra sin registrar la orden |
| P7 | Repetir P5 y pulsar CONFIRMAR CARGA | Mensaje de éxito; la orden aparece en estado CARGADA |
| P8 | Volver a cargar `orden_3363742.xlsx` | Alerta amarilla: la orden ya existe, con fecha y usuario. CONFIRMAR CARGA deshabilitado |
| P9 | Pulsar NO REEMPLAZAR | Se cierra sin cambios; sigue una sola orden CARGADA |
| P10 | Repetir P8, pulsar REEMPLAZAR, dejar la novedad vacía | CONFIRMAR CARGA sigue deshabilitado |
| P11 | Escribir la novedad y CONFIRMAR CARGA | La orden anterior pasa a CANCELADA y la nueva queda CARGADA |
| P12 | Clic en la orden CANCELADA | Detalle con quién canceló, cuándo y la novedad. DESCARGAR ARCHIVO ORIGINAL baja el Excel |
| P13 | Copiar `orden_3363742.xlsx`, borrar un código de material (columna E) y poner 0 en una Cantidad PT (columna D); cargarlo | Lista de errores con fila, columna y regla (VAL-10 y VAL-09) |
| P14 | Filtrar por estado y buscar por número de orden o PT | El listado se filtra |

## 5. Revisar el Audit Trail de CU-03

En pgAdmin o psql, sobre `ebr_pruebas_db`:

```sql
SELECT timestamp, evento, resultado, entidad_id, datos_nuevos
FROM audit_trail
WHERE modulo = 'CU-03'
ORDER BY timestamp DESC;
```

Eventos esperados: `CARGA_ORDEN_EXITOSA`, `ORDEN_REEMPLAZADA` (con la novedad), `CARGA_ORDEN_RECHAZADA`,
`CARGA_ORDEN_CANCELADA` y `CARGA_ORDEN_ACCESO_DENEGADO`.

## 6. Qué se agregó para CU-03

| Archivo | Cambio |
| --- | --- |
| app/models/modelo_orden_trabajo.py | Nuevo. Tablas `ordenes_trabajo` y `lineas_material_orden` |
| app/services/servicio_carga_ordenes.py | Nuevo. Lectura de la hoja BOM, reglas VAL-01 a VAL-14, registro y reemplazo |
| app/schemas/esquema_orden_trabajo.py | Nuevo. Modelos de respuesta |
| app/controllers/controlador_ordenes.py | Nuevo. Endpoints `/ebr/ordenes...` y la página del repositorio |
| app/views/ordenes_ebr.html | Nuevo. Repositorio, carga, vista previa, alerta de reemplazo y detalle |
| app/models/__init__.py, app/main.py | Registran el modelo y el router nuevos |
| app/controllers/controlador_ebr.py | `/ebr/me` devuelve también el rol |
| app/views/principal_ebr.html | Botón al repositorio de órdenes |
| scripts/preparar_bd_pruebas.py | Nuevo. Crea la base de pruebas, tablas y usuarios |
| tests/test_cu03_carga_ordenes.py, tests/datos/ | Nuevos. 28 pruebas automáticas |
| requirements.txt | Nuevo. Agrega openpyxl 3.1.5 (lectura de Excel) y pytest |
