"""Arma la imagen grande (atlas) con todas las Polaroids y el manifest que lee el mundo.

Se publican DOS atlas: el del periodo actual y el del siguiente (atlas_0 y atlas_1, según si el
número de periodo es par o impar). Así, cuando llega la hora de rotar, la imagen nueva ya está
publicada desde horas antes y todos los jugadores cambian a la vez.
"""

import hashlib
import io
import json
from pathlib import Path

from PIL import Image

from . import polaroid as pol


def periodo(ts, horas):
    return int(ts // (horas * 3600))


def _ventana(lista, cupo, p):
    """Elige `cupo` elementos de la lista, rotando de a `cupo` en cada periodo."""
    if len(lista) <= cupo:
        return list(lista)
    inicio = (p * cupo) % len(lista)
    return [lista[(inicio + i) % len(lista)] for i in range(cupo)]


def elegir(fotos, cfg_t, p):
    """Devuelve la lista de pinzas: primero las VIP y luego las comunitarias (None = vacía)."""
    vip = sorted([f for f in fotos if f["tipo"] == "vip"], key=lambda f: f["aprobada"])
    com = sorted([f for f in fotos if f["tipo"] == "comunidad"], key=lambda f: f["aprobada"])
    elegidas_vip = _ventana(vip, cfg_t["vip"], p)
    elegidas_com = _ventana(com, cfg_t["comunitarias"], p)
    pinzas = elegidas_vip + [None] * (cfg_t["vip"] - len(elegidas_vip))
    pinzas += elegidas_com + [None] * (cfg_t["comunitarias"] - len(elegidas_com))
    return pinzas


def celdas(cfg_img):
    """Rectángulo de cada Polaroid dentro del atlas, en píxeles y en UV (v desde abajo)."""
    tam, cols, filas = cfg_img["tamano_atlas"], cfg_img["columnas"], cfg_img["filas"]
    cw, ch = tam // cols, tam // filas
    # Polaroid escalada para caber en la celda con un pequeño margen (evita que se mezclen al filtrar)
    esc = min((cw - 8) / pol.ANCHO, (ch - 8) / pol.ALTO)
    pw, ph = int(pol.ANCHO * esc), int(pol.ALTO * esc)
    out = []
    for i in range(cols * filas):
        cx, cy = i % cols, i // cols
        x = cx * cw + (cw - pw) // 2
        y = cy * ch + (ch - ph) // 2
        out.append({"x": x, "y": y, "w": pw, "h": ph,
                    "u0": round(x / tam, 6), "v0": round(1 - (y + ph) / tam, 6),
                    "u1": round((x + pw) / tam, 6), "v1": round(1 - y / tam, 6)})
    return out


def construir_atlas(pinzas, carpeta_fotos, cfg_img, textos, vacias):
    tam = cfg_img["tamano_atlas"]
    atlas = Image.new("RGB", (tam, tam), (24, 22, 21))
    invitacion = None
    for i, (f, c) in enumerate(zip(pinzas, celdas(cfg_img))):
        if f is not None:
            img = Image.open(Path(carpeta_fotos) / f["archivo"]).convert("RGB")
        elif vacias == "invitacion":
            invitacion = invitacion or pol.hacer_invitacion(cfg_img, textos)
            img = invitacion
        else:
            continue
        atlas.paste(img.resize((c["w"], c["h"]), Image.LANCZOS), (c["x"], c["y"]))
    return atlas


def guardar_imagen(img, ruta, cfg_img):
    if cfg_img["formato"].lower() in ("jpg", "jpeg"):
        img.save(ruta, "JPEG", quality=cfg_img["calidad"], optimize=True, progressive=False)
    else:
        img.save(ruta, "PNG", optimize=True)


def construir_sitio(fotos, carpeta_fotos, cfg, ahora, salida):
    """Escribe atlas_0/atlas_1 + manifest.json + index.html en `salida`. Devuelve un hash del contenido."""
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    cfg_t, cfg_img, textos = cfg["tendedero"], cfg["imagen"], cfg["textos"]
    total = cfg_img["columnas"] * cfg_img["filas"]
    if cfg_t["vip"] + cfg_t["comunitarias"] != total:
        raise ValueError(f"vip ({cfg_t['vip']}) + comunitarias ({cfg_t['comunitarias']}) tiene que ser "
                         f"igual a columnas x filas ({total}) en config.yml")
    horas = cfg_t["horas_rotacion"]
    p = periodo(ahora, horas)
    ext = "jpg" if cfg_img["formato"].lower() in ("jpg", "jpeg") else "png"
    periodos, h = [], hashlib.sha256()
    for q in (p, p + 1):
        pinzas = elegir(fotos, cfg_t, q)
        atlas = construir_atlas(pinzas, carpeta_fotos, cfg_img, textos, cfg_t["vacias"])
        nombre = f"atlas_{q % 2}.{ext}"
        buf = io.BytesIO()
        guardar_imagen(atlas, buf, cfg_img)
        (salida / nombre).write_bytes(buf.getvalue())
        h.update(buf.getvalue())
        periodos.append({
            "periodo": q,
            "desde": q * horas * 3600,
            "hasta": (q + 1) * horas * 3600,
            "atlas": q % 2,
            "pinzas": [{"tipo": "vip" if i < cfg_t["vip"] else "comunidad",
                        "ocupada": f is not None,
                        "autor": f["autor"] if f else ""} for i, f in enumerate(pinzas)],
        })
    manifest = {
        "version": h.hexdigest()[:12],
        "generado": int(ahora),
        "horas_rotacion": horas,
        "columnas": cfg_img["columnas"], "filas": cfg_img["filas"],
        "vacias": cfg_t["vacias"],
        "celdas": celdas(cfg_img),
        "periodos": periodos,
    }
    texto = json.dumps(manifest, ensure_ascii=False, indent=1)
    (salida / "manifest.json").write_text(texto, encoding="utf-8")
    plantilla = Path(__file__).resolve().parent.parent / "plantilla_web" / "index.html"
    if plantilla.exists():
        html = plantilla.read_text(encoding="utf-8")
        html = (html.replace("{{ATLAS}}", f"atlas_{p % 2}.{ext}")
                    .replace("{{VERSION}}", manifest["version"])
                    .replace("{{FOTOS}}", str(len(fotos))))
        (salida / "index.html").write_text(html, encoding="utf-8")
    (salida / ".nojekyll").write_text("")
    return manifest["version"]
