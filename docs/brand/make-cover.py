"""Portada del README a partir de un frame del video y del sistema de diseño de `docu`.

`docs/brand/docu-demo.mp4` es una animación de 10 s: fuentes → documento verificado → artefactos. Un
`.mp4` del repositorio no se reproduce en una cabecera de README (GitHub sólo sirve videos subidos con
su editor web), así que la portada se compone con un frame real del video más la identidad del
proyecto. El video queda como material de origen y **no se anuncia en el README**: no se promete lo que
no se puede ver.

Se ejecuta a mano cuando cambia el video o la paleta:

    python docs/brand/make-cover.py docs/brand/frame-video.png docs/brand/portada.png

Requiere Pillow (dependencia de desarrollo, no del paquete).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ANCHO, ALTO = 1280, 720
FONDO = (20, 17, 14)
ORO = (242, 193, 78)
ORO_SUAVE = (232, 184, 75)
GRIS = (185, 175, 160)
GRIS_APAGADO = (140, 130, 114)
AZUL = (74, 158, 255)

FUENTES = (
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\seguisb.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
)
MONO = (r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\cour.ttf")


def _fuente(rutas: tuple[str, ...], tamano: int) -> ImageFont.FreeTypeFont:
    for ruta in rutas:
        if Path(ruta).is_file():
            return ImageFont.truetype(ruta, tamano)
    return ImageFont.load_default(size=tamano)


def _espaciado(dibujo: ImageDraw.ImageDraw, xy: tuple[int, int], texto: str, fuente, extra: int, fill) -> int:
    """Texto con espaciado entre letras: el logotipo respira, el texto normal no."""
    x, y = xy
    for caracter in texto:
        dibujo.text((x, y), caracter, font=fuente, fill=fill)
        x += dibujo.textlength(caracter, font=fuente) + extra
    return int(x)


def componer(frame: Path, destino: Path) -> Path:
    lienzo = Image.new("RGB", (ANCHO, ALTO), FONDO)
    if frame.is_file():
        arte = Image.open(frame).convert("RGB").resize((ANCHO, ALTO), Image.LANCZOS)
        # Se oscurece apenas el arte para que el logotipo tenga contraste sin tapar la ilustración.
        velo = Image.new("RGB", (ANCHO, ALTO), FONDO)
        lienzo = Image.blend(arte, velo, 0.22)
    dibujo = ImageDraw.Draw(lienzo)

    # Logotipo y promesa, arriba a la izquierda: zona oscura del frame.
    titulo = _fuente(FUENTES, 74)
    _espaciado(dibujo, (66, 40), "docu", titulo, 5, ORO)

    subtitulo = _fuente(FUENTES, 25)
    dibujo.text(
        (70, 132),
        "documentación técnica que se puede verificar",
        font=subtitulo,
        fill=GRIS,
    )

    # Regla corta en azul: el mismo acento que el check del video.
    dibujo.line([(70, 176), (170, 176)], fill=AZUL, width=3)

    # Pie: la promesa concreta, en monoespaciada como una cita.
    mono = _fuente(MONO, 19)
    dibujo.text(
        (70, 636),
        "cada afirmación cita archivo#línea · extractivo · 0 USD",
        font=mono,
        fill=GRIS_APAGADO,
    )

    # Sello de licencia, abajo a la derecha.
    sello = _fuente(FUENTES, 18)
    etiqueta = "MIT · v0.1.0"
    ancho_etiqueta = dibujo.textlength(etiqueta, font=sello)
    x = ANCHO - 70 - ancho_etiqueta
    dibujo.text((x, 636), etiqueta, font=sello, fill=GRIS_APAGADO)

    destino.parent.mkdir(parents=True, exist_ok=True)
    lienzo.save(destino, format="PNG", optimize=True)
    return destino


def main(argv: list[str]) -> int:
    frame = Path(argv[1]) if len(argv) > 1 else Path("docs/brand/frame-video.png")
    destino = Path(argv[2]) if len(argv) > 2 else Path("docs/brand/portada.png")
    print(componer(frame, destino))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
