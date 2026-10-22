from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/admin", tags=["Panel de Administración (UI)"])
templates = Jinja2Templates(directory="app/views")


@router.get("/panel", response_class=HTMLResponse)
async def mostrar_panel_admin(request: Request):
    """
    Renderiza la pantalla del panel de administración.
    La protección real ocurre en el navegador: sin un JWT válido guardado,
    el JS no puede llamar a ningún endpoint de /admin/usuarios/.
    """
    return templates.TemplateResponse(request=request, name="panel_administracion.html")