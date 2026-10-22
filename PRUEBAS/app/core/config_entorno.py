import os
from dotenv import load_dotenv

load_dotenv()


class ConfiguracionEntorno:
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRACION_MINUTOS: int = int(os.getenv("JWT_EXPIRACION_MINUTOS", "30"))
    AUDIT_RETENTION_DAYS: int = int(os.getenv("AUDIT_RETENTION_DAYS", "365"))  
    EBR_SESSION_EXPIRACION_MINUTOS: int = int(os.getenv("EBR_SESSION_EXPIRACION_MINUTOS", "30"))

    def __init__(self):
        if not self.JWT_SECRET_KEY:
            raise ValueError("ERROR: JWT_SECRET_KEY no está configurada en el archivo .env")


configuracion = ConfiguracionEntorno()