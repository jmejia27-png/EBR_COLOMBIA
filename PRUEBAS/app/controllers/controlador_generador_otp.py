from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.conexion_postgres import SessionLocal
from app.services.servicio_generador_otp import ServicioGeneradorOTP
from app.schemas.esquema_token_otp import SolicitudOTP, RespuestaOTP

router = APIRouter(prefix="/otp", tags=["CU-00 Generador OTP"])
templates = Jinja2Templates(directory="app/views")

def obtener_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/", response_class=HTMLResponse)
async def mostrar_vista_otp(request: Request):
    """Renderiza la pantalla web interactiva del Generador OTP."""
    return templates.TemplateResponse(
        request=request, 
        name="generador_tokens.html"
    )

@router.post("/generar", response_model=RespuestaOTP)
async def generar_otp_endpoint(
    request: Request,
    datos: SolicitudOTP,
    db: Session = Depends(obtener_db)
):
    """Procesa la solicitud de token, valida identidad y registra el evento en Audit Trail."""
    ip_cliente = request.client.host if request.client else "127.0.0.1"
    
    resultado = ServicioGeneradorOTP.generar_otp_para_usuario(
        db=db,
        username=datos.username,
        password=datos.password,
        ip_address=ip_cliente
    )
    
    if not resultado["exito"]:
        return JSONResponse(status_code=400, content=resultado)
        
    return resultado