# app/services/pdf_basico.py
# Generador de PDF mínimo, sin dependencias externas, para los formatos del EBR.
# Usa las fuentes estándar del PDF (Helvetica), codificación WinAnsi (español con tildes y ñ),
# líneas, rectángulos y texto. Suficiente para formatos tabulares con firmas.
import zlib
from datetime import datetime

# Anchos de carácter (1/1000 de punto) para los bytes 32..255 en WinAnsi (tablas AFM de Adobe).
_ANCHO_HELVETICA = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556,
    556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556,
    556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584, 761,
    556, 556, 222, 556, 333, 1000, 556, 556, 333, 1000, 667, 333, 1000, 556, 611, 556, 556, 222, 222, 333, 333, 350, 556, 1000,
    333, 1000, 500, 333, 944, 556, 500, 667, 278, 333, 556, 556, 556, 556, 260, 556, 333, 737, 370, 556, 584, 333, 737, 333,
    400, 584, 333, 333, 333, 556, 537, 278, 333, 333, 365, 556, 834, 834, 834, 611, 667, 667, 667, 667, 667, 667, 1000, 722,
    667, 667, 667, 667, 278, 278, 278, 278, 722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,
    556, 556, 556, 556, 556, 556, 889, 500, 556, 556, 556, 556, 278, 278, 278, 278, 556, 556, 556, 556, 556, 556, 556, 584,
    611, 556, 556, 556, 556, 500, 556, 500,
]
_ANCHO_HELVETICA_BOLD = [
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556,
    556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611,
    611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584, 761,
    556, 556, 278, 556, 500, 1000, 556, 556, 333, 1000, 667, 333, 1000, 556, 611, 556, 556, 278, 278, 500, 500, 350, 556, 1000,
    333, 1000, 556, 333, 944, 556, 500, 667, 278, 333, 556, 556, 556, 556, 280, 556, 333, 737, 370, 556, 584, 333, 737, 333,
    400, 584, 333, 333, 333, 611, 556, 278, 333, 333, 365, 556, 834, 834, 834, 611, 722, 722, 722, 722, 722, 722, 1000, 722,
    667, 667, 667, 667, 278, 278, 278, 278, 722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,
    556, 556, 556, 556, 556, 556, 889, 556, 556, 556, 556, 556, 278, 278, 278, 278, 611, 611, 611, 611, 611, 611, 611, 584,
    611, 611, 611, 611, 611, 556, 611, 556,
]

FUENTES = {
    "normal": ("F1", "Helvetica", _ANCHO_HELVETICA),
    "negrita": ("F2", "Helvetica-Bold", _ANCHO_HELVETICA_BOLD),
    "cursiva": ("F3", "Helvetica-Oblique", _ANCHO_HELVETICA),
}


def _a_winansi(texto: str) -> bytes:
    return str(texto).replace("\r", " ").replace("\n", " ").replace("\t", " ").encode("cp1252", errors="replace")


def ancho_texto(texto: str, tam: float, fuente: str = "normal") -> float:
    tabla = FUENTES[fuente][2]
    return sum(tabla[b - 32] if b >= 32 else 0 for b in _a_winansi(texto)) * tam / 1000.0


def partir_texto(texto: str, ancho: float, tam: float, fuente: str = "normal") -> list[str]:
    """Divide el texto en líneas que caben en el ancho indicado (corta palabras muy largas)."""
    lineas: list[str] = []
    for parrafo in str(texto or "").replace("\r", "").split("\n"):
        actual = ""
        for palabra in parrafo.split(" "):
            candidato = palabra if not actual else actual + " " + palabra
            if ancho_texto(candidato, tam, fuente) <= ancho:
                actual = candidato
                continue
            if actual:
                lineas.append(actual)
            while ancho_texto(palabra, tam, fuente) > ancho and len(palabra) > 1:   # palabra más ancha que la celda
                corte = len(palabra)
                while corte > 1 and ancho_texto(palabra[:corte], tam, fuente) > ancho:
                    corte -= 1
                lineas.append(palabra[:corte])
                palabra = palabra[corte:]
            actual = palabra
        lineas.append(actual)
    return lineas or [""]


def _escapar(datos: bytes) -> bytes:
    return datos.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


class Pagina:
    """Coordenadas con origen arriba a la izquierda (y crece hacia abajo), en puntos."""

    def __init__(self, ancho: float, alto: float):
        self.ancho, self.alto = ancho, alto
        self.ops: list[bytes] = []

    def _y(self, y: float) -> float:
        return self.alto - y

    def texto(self, x, y, texto, tam=9, fuente="normal", color=(0, 0, 0), alinear="izq", ancho=None):
        """y es la línea base del texto. alinear: izq | centro | der (respecto a x..x+ancho)."""
        if alinear != "izq" and ancho is not None:
            w = ancho_texto(texto, tam, fuente)
            x = x + (ancho - w) / 2 if alinear == "centro" else x + ancho - w
        nombre = FUENTES[fuente][0]
        r, g, b = color
        self.ops.append(b"BT %.3f %.3f %.3f rg /%s %.2f Tf %.2f %.2f Td (" % (r, g, b, nombre.encode(), tam, x, self._y(y))
                        + _escapar(_a_winansi(texto)) + b") Tj ET")

    def texto_rotado(self, cx, cy, texto, tam, grados, fuente="negrita", color=(0.9, 0.9, 0.9)):
        import math
        a = math.radians(grados)
        w = ancho_texto(texto, tam, fuente)
        c, s = math.cos(a), math.sin(a)
        x = cx - (w / 2) * c + (tam / 3) * s
        y = self._y(cy) - (w / 2) * s - (tam / 3) * c
        r, g, b = color
        self.ops.append(b"BT %.3f %.3f %.3f rg /%s %.2f Tf %.4f %.4f %.4f %.4f %.2f %.2f Tm (" % (
            r, g, b, FUENTES[fuente][0].encode(), tam, c, s, -s, c, x, y) + _escapar(_a_winansi(texto)) + b") Tj ET")

    def linea(self, x1, y1, x2, y2, grosor=0.6, color=(0, 0, 0)):
        self.ops.append(b"q %.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f l S Q" % (
            *color, grosor, x1, self._y(y1), x2, self._y(y2)))

    def rect(self, x, y, w, h, relleno=None, borde=(0, 0, 0), grosor=0.6):
        partes = [b"q"]
        if relleno:
            partes.append(b"%.3f %.3f %.3f rg" % relleno)
        if borde:
            partes.append(b"%.3f %.3f %.3f RG %.2f w" % (*borde, grosor))
        op = b"B" if relleno and borde else (b"f" if relleno else b"S")
        partes.append(b"%.2f %.2f %.2f %.2f re %s Q" % (x, self._y(y + h), w, h, op))
        self.ops.append(b" ".join(partes))


class DocumentoPDF:
    def __init__(self, ancho=792.0, alto=612.0, titulo="", autor=""):
        self.ancho, self.alto = ancho, alto
        self.titulo, self.autor = titulo, autor
        self.paginas: list[Pagina] = []

    def nueva_pagina(self) -> Pagina:
        p = Pagina(self.ancho, self.alto)
        self.paginas.append(p)
        return p

    def generar(self, fecha: datetime | None = None) -> bytes:
        objetos: list[bytes] = []

        def agregar(contenido: bytes) -> int:
            objetos.append(contenido)
            return len(objetos)

        catalogo = agregar(b"")          # se completa al final
        raiz_paginas = agregar(b"")
        fuentes = {
            nombre: agregar(b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>" % base.encode())
            for nombre, base, _ in FUENTES.values()
        }
        recursos = b"<< /Font << " + b" ".join(b"/%s %d 0 R" % (n.encode(), i) for n, i in fuentes.items()) + b" >> >>"
        hijos = []
        for p in self.paginas:
            flujo = zlib.compress(b"\n".join(p.ops))
            contenido = agregar(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(flujo) + flujo + b"\nendstream")
            hijos.append(agregar(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Resources %s /Contents %d 0 R >>"
                                 % (raiz_paginas, p.ancho, p.alto, recursos, contenido)))
        objetos[raiz_paginas - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
            b" ".join(b"%d 0 R" % h for h in hijos), len(hijos))
        objetos[catalogo - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % raiz_paginas
        f = (fecha or datetime.now()).strftime("D:%Y%m%d%H%M%S")
        info = agregar(b"<< /Title (" + _escapar(_a_winansi(self.titulo)) + b") /Author (" + _escapar(_a_winansi(self.autor))
                       + b") /Producer (EBR Yobel) /CreationDate (" + f.encode() + b") >>")

        salida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        posiciones = []
        for i, obj in enumerate(objetos, 1):
            posiciones.append(len(salida))
            salida += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
        inicio_xref = len(salida)
        salida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
        for pos in posiciones:
            salida += b"%010d 00000 n \n" % pos
        salida += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objetos) + 1, catalogo, info, inicio_xref)
        return bytes(salida)
