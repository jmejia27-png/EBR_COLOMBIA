from passlib.context import CryptContext

# Configuración del contexto con Argon2
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def obtener_password_hash(password: str) -> str:
    """Genera el hash seguro de la contraseña usando Argon2."""
    return pwd_context.hash(password)

def verificar_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica si la contraseña ingresada coincide con el hash almacenado."""
    return pwd_context.verify(plain_password, hashed_password)