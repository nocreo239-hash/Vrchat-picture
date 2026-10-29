"""Convierte una foto en una Polaroid con el nombre del autor escrito en el marco."""

import io
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

FUENTE = Path(__file__).resolve().parent.parent / "fuentes" / "Caveat.ttf"

# Proporciones de una Polaroid clásica: 88 x 107 mm, foto cuadrada de 79 mm
ANCHO, ALTO = 800, 973
MARGEN = 41                      # lados y arriba
FOTO = ANCHO - 2 * MARGEN        # 718: foto cuadrada
ZONA_TEXTO = (MARGEN + FOTO, ALTO)


def _color(hex_):
    hex_ = hex_.lstrip("#")
    return tuple(int(hex_[i:i + 2], 16) for i in (0, 2, 4))


def _fuente(tam, peso=650):
    f = ImageFont.truetype(str(FUENTE), tam)
    try:
        f.set_variation_by_axes([peso])
    except Exception:
        pass
    return f


def limpiar_nombre(nombre, max_letras=22):
    """Deja solo letras que la fuente sabe dibujar (latino y cirílico); quita emojis y símbolos raros."""
    limpio = []
    for c in unicodedata.normalize("NFC", nombre or ""):
        cat = unicodedata.category(c)
        o = ord(c)
        if cat[0] in "LNP" or c == " ":
            if o < 0x0250 or 0x0400 <= o <= 0x04FF:
                limpio.append(c)
    texto = " ".join("".join(limpio).split())
    if len(texto) > max_letras:
        texto = texto[:max_letras - 1].rstrip() + "…"
    return texto or "Anónimo"


def _texto_centrado(dibujo, texto, caja, color, tam_max, tam_min=40, peso=650):
    x0, y0, x1, y1 = caja
    ancho_max = x1 - x0
    for tam in range(tam_max, tam_min - 1, -4):
        f = _fuente(tam, peso)
        l, t, r, b = dibujo.textbbox((0, 0), texto, font=f)
        if r - l <= ancho_max:
            break
    x = x0 + (ancho_max - (r - l)) / 2 - l
    y = y0 + ((y1 - y0) - (b - t)) / 2 - t
    dibujo.text((x, y), texto, font=f, fill=color)


def _estrella(dibujo, cx, cy, r, color):
    import math
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    dibujo.polygon(pts, fill=color)


def hacer_polaroid(foto_bytes, autor, cfg_img, vip=False):
    """foto_bytes: la imagen original. Devuelve una imagen PIL RGB de 800 x 973."""
    foto = Image.open(io.BytesIO(foto_bytes))
    foto = ImageOps.exif_transpose(foto).convert("RGB")
    foto = ImageOps.fit(foto, (FOTO, FOTO), method=Image.LANCZOS, centering=(0.5, 0.45))

    marco = Image.new("RGB", (ANCHO, ALTO), _color(cfg_img["color_marco"]))
    marco.paste(foto, (MARGEN, MARGEN))
    d = ImageDraw.Draw(marco)
    # Borde muy fino alrededor de la foto, como el papel real
    d.rectangle([MARGEN - 1, MARGEN - 1, MARGEN + FOTO, MARGEN + FOTO], outline=(205, 200, 190))

    nombre = limpiar_nombre(autor, cfg_img.get("max_letras_nombre", 22))
    caja = (MARGEN + 20, MARGEN + FOTO + 18, ANCHO - MARGEN - 20, ALTO - 28)
    if vip:
        _estrella(d, ANCHO - MARGEN - 30, MARGEN + FOTO + 48, 24, _color(cfg_img["color_vip"]))
        caja = (MARGEN + 20, caja[1], ANCHO - MARGEN - 70, caja[3])
    _texto_centrado(d, nombre, caja, _color(cfg_img["color_texto"]), tam_max=118)
    return marco


def hacer_invitacion(cfg_img, textos):
    """Polaroid vacía para las pinzas libres: invita a mandar una foto."""
    marco = Image.new("RGB", (ANCHO, ALTO), _color(cfg_img["color_marco"]))
    d = ImageDraw.Draw(marco)
    d.rectangle([MARGEN, MARGEN, MARGEN + FOTO, MARGEN + FOTO], fill=(38, 34, 32))
    _texto_centrado(d, textos["invitacion_titulo"], (MARGEN + 40, MARGEN + 230, MARGEN + FOTO - 40, MARGEN + 380),
                    (240, 232, 214), tam_max=110)
    _texto_centrado(d, textos["invitacion_texto"], (MARGEN + 40, MARGEN + 390, MARGEN + FOTO - 40, MARGEN + 480),
                    (200, 190, 170), tam_max=70, peso=500)
    return marco
