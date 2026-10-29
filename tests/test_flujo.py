"""Prueba el flujo completo con un Discord falso: envío, revisión, aprobación, VIP, rechazo,
quitar publicada, caducidad, rotación y atlas. Corre con:  python -m tests.test_flujo"""

import io
import json
import random
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from tendedero import atlas
from tendedero.procesar import Datos, Tendedero, APROBAR, VIP, RECHAZAR
import yaml

RAIZ = Path(__file__).resolve().parent.parent
ADMIN_ROL, BOT, ADMIN, NOADMIN = "900", "1", "50", "60"


def foto_de_prueba(n):
    r = random.Random(n)
    img = Image.new("RGB", (r.randint(600, 1600), r.randint(600, 1600)), tuple(r.randint(30, 220) for _ in range(3)))
    d = ImageDraw.Draw(img)
    for _ in range(12):
        x, y = r.randint(0, img.width), r.randint(0, img.height)
        d.ellipse([x - 120, y - 120, x + 120, y + 120], fill=tuple(r.randint(0, 255) for _ in range(3)))
    d.text((20, 20), f"FOTO {n}", fill=(255, 255, 255))
    b = io.BytesIO(); img.save(b, "JPEG"); return b.getvalue()


class DiscordFalso:
    def __init__(self):
        self.canales = {}       # canal -> {id: msg}
        self.archivos = {}      # url -> bytes
        self.siguiente = 1000
        self.reloj_ms = 1_800_000_000_000
        self.miembros = {
            ADMIN: {"nick": "Admin Cuervo", "roles": [ADMIN_ROL]},
            NOADMIN: {"nick": None, "roles": []},
        }

    def _id(self):
        # IDs con forma de Discord (llevan la fecha dentro), para probar la recuperación
        self.siguiente += 1
        return str(((self.reloj_ms - 1420070400000) << 22) + self.siguiente)

    # lo que escribe un usuario
    def usuario_manda(self, canal, uid, nombre, n_fotos=1, texto=""):
        adj = []
        for i in range(n_fotos):
            url = f"https://cdn/{self._id()}.jpg"
            self.archivos[url] = foto_de_prueba(self.siguiente)
            adj.append({"url": url, "filename": "f.jpg", "content_type": "image/jpeg"})
        mid = self._id()
        self.canales.setdefault(canal, {})[mid] = {"id": mid, "author": {"id": uid, "global_name": nombre, "username": nombre.lower()},
                                                   "attachments": adj, "content": texto, "reacciones": {}}
        return mid

    def reacciona(self, canal, mid, emoji, uid):
        self.canales[canal][mid]["reacciones"].setdefault(emoji, []).append({"id": uid, "username": "u" + uid, "global_name": "Admin Cuervo" if uid == ADMIN else "Cualquiera"})

    # interfaz de Discord
    def quien_soy(self): return {"id": BOT}
    def mensajes_despues(self, canal, despues=None):
        ms = sorted(self.canales.get(canal, {}).values(), key=lambda m: int(m["id"]))
        return [m for m in ms if despues is None or int(m["id"]) > int(despues)]
    def mensajes_recientes(self, canal, limite=100):
        return sorted(self.canales.get(canal, {}).values(), key=lambda m: -int(m["id"]))[:limite]
    def mensaje(self, canal, mid): return self.canales.get(canal, {}).get(mid)
    def reacciones(self, canal, mid, emoji):
        m = self.mensaje(canal, mid); return list(m["reacciones"].get(emoji, [])) if m else []
    def miembro(self, servidor, uid): return self.miembros.get(uid, {"roles": []})
    def descargar(self, url): return self.archivos[url]
    def enviar(self, canal, texto, archivo=None, nombre_archivo="f.jpg", menciones=None):
        mid = self._id(); adj = []
        if archivo is not None:
            url = f"https://cdn/rev{mid}.jpg"; self.archivos[url] = archivo
            adj = [{"url": url, "filename": nombre_archivo, "content_type": "image/jpeg"}]
        self.canales.setdefault(canal, {})[mid] = {"id": mid, "author": {"id": BOT, "bot": True}, "attachments": adj, "content": texto, "reacciones": {}}
        return {"id": mid}
    def reaccionar(self, canal, mid, emoji): self.reacciona(canal, mid, emoji, BOT)
    def editar(self, canal, mid, texto): self.canales[canal][mid]["content"] = texto
    def borrar(self, canal, mid): self.canales.get(canal, {}).pop(mid, None)


def main():
    cfg = yaml.safe_load((RAIZ / "config.yml").read_text(encoding="utf-8"))
    cfg["discord"].update(servidor_id="10", canal_envios_id="20", canal_revision_id="30", roles_admin_ids=[ADMIN_ROL])
    tmp = Path(tempfile.mkdtemp())
    dc = DiscordFalso()
    ahora = 1_800_000_000

    def pasada(t):
        tt = Tendedero(cfg, dc, Datos(tmp), ahora=t)
        pub, ver = tt.pasada(tmp / "_site")
        return tt, pub

    # 1) tres usuarios mandan fotos; uno manda texto sin foto
    dc.usuario_manda("20", "70", "María 🌸")
    dc.usuario_manda("20", "71", "xX_CuervoNegro_Xx", n_fotos=2)
    dc.usuario_manda("20", "72", "Пётр")
    dc.usuario_manda("20", "73", "Solo texto", n_fotos=0, texto="hola")
    tt, pub = pasada(ahora)
    pend = tt.d.estado["pendientes"]
    assert len(pend) == 4, pend
    rev = dc.canales["30"]
    assert all(set(m["reacciones"]) == {APROBAR, VIP, RECHAZAR} for m in rev.values()), "faltan reacciones del bot"
    publicos = [m for m in dc.canales["20"].values() if not m["author"].get("bot")]
    assert len(publicos) == 1 and publicos[0]["content"] == "hola", "debía borrar solo los mensajes con foto"
    avisos = [m for m in dc.canales["20"].values() if m["author"].get("bot")]
    assert len(avisos) == 3, avisos
    print("1 ok: 4 fotos pasadas a revisión, originales borrados, 3 avisos")

    # 2) un no-admin aprueba (no cuenta); el admin aprueba una, otra VIP y rechaza otra
    ids = [p["revision_id"] for p in pend]
    dc.reacciona("30", ids[0], APROBAR, NOADMIN)
    dc.reacciona("30", ids[1], VIP, ADMIN)
    dc.reacciona("30", ids[2], APROBAR, ADMIN)
    dc.reacciona("30", ids[3], RECHAZAR, ADMIN)
    tt, pub = pasada(ahora + 600)
    fotos = tt.d.fotos
    assert len(fotos) == 2, fotos
    assert {f["tipo"] for f in fotos} == {"vip", "comunidad"}
    assert len(tt.d.estado["pendientes"]) == 1, "la del no-admin debe seguir pendiente"
    assert "Rechazada" in dc.canales["30"][ids[3]]["content"]
    print("2 ok: VIP + comunitaria aprobadas, rechazo aplicado, el no-admin no cuenta")

    # 3) avisos se borran después de 60 min
    tt, _ = pasada(ahora + 3700)
    assert not [m for m in dc.canales["20"].values() if m["author"].get("bot")], "los avisos no se borraron"
    print("3 ok: avisos borrados a la hora")

    # 4) muchas comunitarias para probar rotación: 30 aprobadas
    for i in range(30):
        dc.usuario_manda("20", str(100 + i), f"Usuario {i}")
    tt, _ = pasada(ahora + 4000)
    for p in tt.d.estado["pendientes"]:
        if p["revision_id"] != ids[0]:
            dc.reacciona("30", p["revision_id"], APROBAR, ADMIN)
    tt, _ = pasada(ahora + 4600)
    com = [f for f in tt.d.fotos if f["tipo"] == "comunidad"]
    assert len(com) == 31, len(com)
    man = json.loads((tmp / "_site" / "manifest.json").read_text(encoding="utf-8"))
    a0 = [x["autor"] for x in man["periodos"][0]["pinzas"][5:]]
    a1 = [x["autor"] for x in man["periodos"][1]["pinzas"][5:]]
    assert a0 != a1 and len(set(a0)) == 15 and len(set(a1)) == 15, "la rotación no cambia las comunitarias"
    assert man["periodos"][0]["pinzas"][0]["ocupada"] and not man["periodos"][0]["pinzas"][1]["ocupada"]
    print("4 ok: 31 comunitarias rotan de a 15 por periodo; VIP fija en la pinza 0")

    # 5) el admin quita la VIP ya publicada con ❌
    vip = [f for f in tt.d.fotos if f["tipo"] == "vip"][0]
    dc.reacciona("30", vip["revision_id"], RECHAZAR, ADMIN)
    tt, _ = pasada(ahora + 5200)
    assert not [f for f in tt.d.fotos if f["tipo"] == "vip"], "la VIP no se quitó"
    print("5 ok: VIP quitada con ❌")

    # 6) 8 días después: todas las comunitarias caducan; la pendiente sigue (14 días)
    tt, pub = pasada(ahora + 8 * 86400)
    assert not tt.d.fotos and len(tt.d.estado["pendientes"]) == 1
    assert not list((tmp / "data" / "fotos").glob("*.jpg")), "quedaron archivos de fotos caducadas"
    tt, _ = pasada(ahora + 15 * 86400)
    assert not tt.d.estado["pendientes"]
    print("6 ok: caducidad de comunitarias (7 d) y pendientes (14 d)")

    # 7) una pasada pierde su estado (no pudo guardar): la foto en revisión se recupera
    estado = (tmp / "data" / "estado.json").read_text(encoding="utf-8")
    dc.reloj_ms = (ahora + 15 * 86400) * 1000
    dc.usuario_manda("20", "300", "Perdida")
    pasada(ahora + 15 * 86400 + 60)
    (tmp / "data" / "estado.json").write_text(estado, encoding="utf-8")  # como si no se hubiera guardado
    tt, _ = pasada(ahora + 15 * 86400 + 120)
    rec = [p for p in tt.d.estado["pendientes"] if p["autor"] == "Perdida"]
    assert len(rec) == 1, tt.d.estado["pendientes"]
    tt, _ = pasada(ahora + 15 * 86400 + 180)
    assert len([p for p in tt.d.estado["pendientes"] if p["autor"] == "Perdida"]) == 1, "se duplicó"
    print("7 ok: foto en revisión recuperada tras perder el estado, sin duplicar")

    # Atlas de muestra para revisar a ojo (con fotos frescas)
    shutil.rmtree(tmp / "data"); dc2 = DiscordFalso()
    global_dc = dc2
    for i, nombre in enumerate(["Allan_Martian", "Valeria ✨", "DJ Cuervo", "Lunita", "Ñandú Pérez", "Neo", "Kurai", "Rosa Negra"]):
        dc2.usuario_manda("20", str(200 + i), nombre)
    t = Tendedero(cfg, dc2, Datos(tmp), ahora=ahora); t.pasada(tmp / "_site")
    for k, p in enumerate(t.d.estado["pendientes"]):
        dc2.reacciona("30", p["revision_id"], VIP if k < 2 else APROBAR, ADMIN)
    t = Tendedero(cfg, dc2, Datos(tmp), ahora=ahora + 600); t.pasada(tmp / "_site")
    salida = RAIZ.parent / "muestra_tendedero"
    shutil.rmtree(salida, ignore_errors=True); shutil.copytree(tmp / "_site", salida)
    print("atlas de muestra en", salida)


if __name__ == "__main__":
    main()
