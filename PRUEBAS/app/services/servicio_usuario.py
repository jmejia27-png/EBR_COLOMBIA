# app/services/servicio_usuarios.py
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.modelo_usuario import Usuario, RolUsuario
from app.schemas.esquema_usuario import UsuarioCrear, UsuarioActualizar
from app.core.seguridad_cifrado import obtener_password_hash
from app.services.servicio_auditoria import ServicioAuditoria


class ServicioUsuarios:

    @staticmethod
    def listar_usuarios(
        db: Session,
        activo: Optional[bool] = None,
        rol: Optional[RolUsuario] = None,
        busqueda: Optional[str] = None,
        pagina: int = 1,
        tamano_pagina: int = 20
    ):
        query = db.query(Usuario)

        if activo is not None:
            query = query.filter(Usuario.activo == activo)
        if rol is not None:
            query = query.filter(Usuario.rol == rol)
        if busqueda:
            patron = f"%{busqueda}%"
            query = query.filter(
                or_(Usuario.username.ilike(patron), Usuario.email.ilike(patron))
            )

        total = query.count()
        usuarios = (
            query.order_by(Usuario.creado_en.desc())
            .offset((pagina - 1) * tamano_pagina)
            .limit(tamano_pagina)
            .all()
        )
        return usuarios, total

    @staticmethod
    def obtener_usuario_por_id(db: Session, usuario_id: str) -> Optional[Usuario]:
        return db.query(Usuario).filter(Usuario.id == usuario_id).first()

    @staticmethod
    def crear_usuario(
        db: Session,
        datos: UsuarioCrear,
        admin_actual: Usuario,
        ip_address: str = "127.0.0.1"
    ) -> Usuario:
        existente = db.query(Usuario).filter(
            or_(Usuario.username == datos.username, Usuario.email == datos.email)
        ).first()
        if existente:
            raise ValueError("El username o el email ya están registrados")

        nuevo_usuario = Usuario(
            username=datos.username,
            email=datos.email,
            nombre_completo=datos.nombre_completo,
            password_hash=obtener_password_hash(datos.password),
            rol=datos.rol,
            activo=True,
            requiere_cambio_password=True
        )
        db.add(nuevo_usuario)
        db.commit()
        db.refresh(nuevo_usuario)

        ServicioAuditoria.registrar_evento(
            db=db,
            usuario_id=admin_actual.id,
            evento="USUARIO_CREADO",
            modulo="ADMIN",
            entidad="usuarios",
            entidad_id=str(nuevo_usuario.id),
            accion="CREAR",
            resultado="EXITO",
            ip_address=ip_address,
            datos_nuevos={
                "username": nuevo_usuario.username,
                "email": nuevo_usuario.email,
                "rol": nuevo_usuario.rol.value if hasattr(nuevo_usuario.rol, "value") else str(nuevo_usuario.rol)
            }
        )
        return nuevo_usuario

    @staticmethod
    def actualizar_usuario(
        db: Session,
        usuario_id: str,
        datos: UsuarioActualizar,
        admin_actual: Usuario,
        ip_address: str = "127.0.0.1"
    ) -> Optional[Usuario]:
        usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
        if not usuario:
            return None

        if datos.username is not None and usuario.username != datos.username:
            raise ValueError("El username no coincide con el usuario indicado en la URL")

        estado_anterior = usuario.activo

        cambios = datos.model_dump(exclude_unset=True)
        cambios.pop("username", None)  # es solo confirmación, no se guarda como cambio

        for campo, valor in cambios.items():
            setattr(usuario, campo, valor)

        db.commit()
        db.refresh(usuario)

        ServicioAuditoria.registrar_evento(
            db=db,
            usuario_id=admin_actual.id,
            evento="USUARIO_ACTUALIZADO",
            modulo="ADMIN",
            entidad="usuarios",
            entidad_id=str(usuario.id),
            accion="ACTUALIZAR",
            resultado="EXITO",
            ip_address=ip_address,
            datos_anteriores={"activo": estado_anterior},
            datos_nuevos={"activo": usuario.activo}
        )
        return usuario

    @staticmethod
    def restablecer_password_temporal(
        db: Session,
        usuario_id: str,
        username_confirmacion: str,
        password_temporal: str,
        admin_actual: Usuario,
        ip_address: str = "127.0.0.1"
    ) -> Usuario:
        usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
        if not usuario:
            raise LookupError("Usuario no encontrado")

        if usuario.username != username_confirmacion:
            raise ValueError("El username no coincide con el usuario indicado en la URL")

        if not usuario.activo:
            raise ValueError("No se puede restablecer la contraseña de un usuario inactivo. Actívelo primero.")

        usuario.password_hash = obtener_password_hash(password_temporal)
        usuario.requiere_cambio_password = True
        db.commit()
        db.refresh(usuario)

        ServicioAuditoria.registrar_evento(
            db=db,
            usuario_id=admin_actual.id,
            evento="PASSWORD_RESETEADA_POR_ADMIN",
            modulo="ADMIN",
            entidad="usuarios",
            entidad_id=str(usuario.id),
            accion="RESTABLECER_PASSWORD",
            resultado="EXITO",
            ip_address=ip_address,
            datos_nuevos={"requiere_cambio_password": True}
        )
        return usuario