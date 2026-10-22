# app/main.py
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from app.controllers import (
    controlador_generador_otp,
    controlador_autenticacion,
    controlador_usuarios,
    controlador_panel_admin,
    controlador_generador_otp, controlador_autenticacion, controlador_usuarios, controlador_panel_admin, controlador_ebr,
    controlador_ordenes,  # CU-03 Cargar orden de trabajo
)

app = FastAPI(
    title="Electronic Batch Record (EBR) - DEMO",
    description="Prototipo funcional de digitalización de Batch Record para Yobel/P&G",
    version="0.1.0"
)

app.include_router(controlador_generador_otp.router)
app.include_router(controlador_autenticacion.router)
app.include_router(controlador_usuarios.router)
app.include_router(controlador_panel_admin.router) 
app.include_router(controlador_ebr.router)  # Agregar el router del controlador EBR
app.include_router(controlador_ordenes.router)  # CU-03 Cargar orden de trabajo

# Hoja de estilos y scripts comunes (diseño blanco / azul Yobel)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def cabeceras_seguridad(request: Request, call_next):
    """Cabeceras básicas de seguridad para todas las respuestas."""
    respuesta = await call_next(request)
    respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
    respuesta.headers.setdefault("X-Frame-Options", "DENY")
    respuesta.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith(("/ebr/ordenes", "/ebr/indicadores", "/ebr/me")):
        respuesta.headers.setdefault("Cache-Control", "no-store")
    return respuesta


@app.get("/")
async def inicio():
    return {
        "sistema": "EBR DEMO",
        "estado": "Servidor Uvicorn Operativo",
        "acceso_otp": "Ingrese a http://127.0.0.1:8000/otp/ para visualizar el Generador de Tokens",
        "acceso_admin": "Ingrese a http://127.0.0.1:8000/admin/panel para el Panel de Administración",
        "acceso_ebr": "Ingrese a http://127.0.0.1:8000/ebr/login para el Login EBR (CU-02) y luego al repositorio de órdenes (CU-03)"
    }