/* =====================================================================
   EBR YOBEL · utilidades comunes de las pantallas internas
   Sesión (token EBR), llamadas a la API, barra lateral y formato.
   ===================================================================== */
(function () {
    'use strict';

    const CLAVE_TOKEN = 'ebr_token';
    const CLAVE_MENU = 'ebr_menu_colapsado';

    function token() { return sessionStorage.getItem(CLAVE_TOKEN); }

    function irALogin() {
        sessionStorage.removeItem(CLAVE_TOKEN);
        window.location.href = '/ebr/login';
    }

    /** Llamada autenticada. Si la sesión venció (401) vuelve al login. */
    async function api(ruta, opciones = {}) {
        const headers = { 'Authorization': `Bearer ${token()}`, ...(opciones.headers || {}) };
        if (opciones.json !== undefined) {
            headers['Content-Type'] = 'application/json';
            opciones = { ...opciones, body: JSON.stringify(opciones.json) };
        }
        const respuesta = await fetch(ruta, { ...opciones, headers });
        if (respuesta.status === 401) { irALogin(); throw new Error('Sesión vencida'); }
        return respuesta;
    }

    /** Extrae un mensaje y la lista de errores de una respuesta fallida. */
    async function leerError(respuesta) {
        try {
            const data = await respuesta.json();
            if (typeof data.detail === 'string') return { mensaje: data.detail, errores: [] };
            if (Array.isArray(data.detail)) return { mensaje: 'Datos inválidos.', errores: [] };
            return { mensaje: data.detail?.mensaje || 'Ocurrió un error inesperado.', errores: data.detail?.errores || [], datos: data.detail };
        } catch (e) {
            return { mensaje: 'No fue posible comunicarse con el servidor.', errores: [] };
        }
    }

    const esc = valor => String(valor ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const fecha = iso => iso ? new Date(iso).toLocaleString('es-CO', { dateStyle: 'short', timeStyle: 'short' }) : '';
    const numero = v => (v === null || v === undefined || v === '') ? '' : Number(v).toLocaleString('es-CO', { maximumFractionDigits: 6 });
    const NOMBRES_ESTADO = { CARGADA: 'Cargada', EN_DESARROLLO: 'En desarrollo', ELIMINADA: 'Eliminada' };
    const estado = e => `<span class="estado estado-${esc(e)}">${esc(NOMBRES_ESTADO[e] || e)}</span>`;

    function mensaje(el, texto, tipo, errores) {
        el.className = `mensaje ${tipo}`;
        el.innerHTML = esc(texto) + (errores && errores.length
            ? '<ul>' + errores.map(e => `<li>${e.fila ? 'Fila ' + esc(e.fila) + ', ' : ''}${e.columna ? 'columna ' + esc(e.columna) + ': ' : ''}${esc(e.mensaje)}</li>`).join('') + '</ul>'
            : '');
    }
    function limpiarMensaje(el) { el.className = 'mensaje'; el.textContent = ''; }

    // ---------------- barra lateral
    function prepararMenu() {
        const app = document.getElementById('app');
        const movil = () => window.matchMedia('(max-width: 900px)').matches;
        try { if (localStorage.getItem(CLAVE_MENU) === '1') app.classList.add('colapsada'); } catch (e) {}

        document.getElementById('btnMenu').addEventListener('click', () => {
            if (movil()) { app.classList.toggle('menu-abierto'); return; }
            app.classList.toggle('colapsada');
            try { localStorage.setItem(CLAVE_MENU, app.classList.contains('colapsada') ? '1' : '0'); } catch (e) {}
        });
        document.getElementById('velo').addEventListener('click', () => app.classList.remove('menu-abierto'));
        document.addEventListener('keydown', e => { if (e.key === 'Escape') app.classList.remove('menu-abierto'); });

        document.getElementById('btnCerrarSesion').addEventListener('click', async () => {
            try { await fetch('/ebr/logout', { method: 'POST', headers: { 'Authorization': `Bearer ${token()}` } }); } catch (e) {}
            irALogin();
        });
    }

    /** Verifica la sesión, pinta el usuario en la barra superior y devuelve sus datos. */
    async function iniciar() {
        if (!token()) { irALogin(); return new Promise(() => {}); }
        prepararMenu();
        const r = await api('/ebr/me');
        if (!r.ok) { irALogin(); return new Promise(() => {}); }
        const yo = await r.json();
        yo.esAdmin = yo.rol === 'admin';
        document.getElementById('usuarioNombre').textContent = yo.nombre_completo || yo.username;
        document.getElementById('usuarioRol').textContent = yo.esAdmin ? 'ADMIN' : 'USER';
        return yo;
    }

    window.EBR = { api, leerError, esc, fecha, numero, estado, mensaje, limpiarMensaje, iniciar, NOMBRES_ESTADO };
})();
