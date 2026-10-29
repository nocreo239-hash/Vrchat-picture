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
        privado = [{"id": "10", "type": 0, "deny": str(1 << 10), "allow": "0"}]
        # servidor -> canales; y cuándo entró el bot a cada uno
        self.servidores = {"10": {"name": "Cuervos", "entro": "2026-01-01T00:00:00",
                                  "canales": [{"id": "20", "type": 0, "name": "manda-tu-polaroid"},
                                              {"id": "30", "type": 0, "name": "revision-polaroids", "permission_overwrites": privado}]}}

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
    def miembro(self, servidor, uid):
        if uid == BOT: return {"roles": [], "joined_at": self.servidores[servidor]["entro"]}
        return self.miembros.get(uid, {"roles": []})
    def roles(self, servidor): return [{"id": servidor, "permissions": str(1 << 10)}, {"id": "admins" + servidor, "permissions": str(1 << 3)}]
    def crear_canal(self, servidor, nombre, tema="", overwrites=None):
        ch = {"id": self._id(), "type": 0, "name": nombre, "topic": tema, "permission_overwrites": overwrites or []}
        self.servidores[servidor]["canales"].append(ch)
        return ch
    def aplicacion(self): return {"id": BOT, "owner": {"id": "500"}}
    def servidor(self, sid): return {"id": sid, "owner_id": self.servidores[sid].get("dueno", "500")}
    def salir_de(self, sid): self.servidores.pop(sid, None)
    def quien_me_anadio(self, sid, bot): return self.servidores[sid].get("anadio")
    def mis_servidores(self): return [{"id": k, "name": v["name"]} for k, v in self.servidores.items()]
    def canales_de(self, servidor): return self.servidores.get(servidor, {}).get("canales", [])
    def descargar(self, url): return self.archivos[url]
    def enviar(self, canal, texto, archivo=None, nombre_archivo="f.jpg", menciones=None, responde_a=None):
        mid = self._id(); adj = []
        if archivo is not None:
            url = f"https://cdn/rev{mid}.jpg"; self.archivos[url] = archivo
            adj = [{"url": url, "filename": nombre_archivo, "content_type": "image/jpeg"}]
        self.canales.setdefault(canal, {})[mid] = {"id": mid, "author": {"id": BOT, "bot": True}, "attachments": adj, "content": texto, "reacciones": {}}
        return {"id": mid}
    def reaccionar(self, canal, mid, emoji): self.reacciona(canal, mid, emoji, BOT)
    def quitar_mi_reaccion(self, canal, mid, emoji):
        r = self.canales[canal][mid]["reacciones"]
        r[emoji] = [u for u in r.get(emoji, []) if u["id"] != BOT]
    def editar(self, canal, mid, texto): self.canales[canal][mid]["content"] = texto
    def borrar(self, canal, mid): self.canales.get(canal, {}).pop(mid, None)


def main():
    cfg = yaml.safe_load((RAIZ / "config.yml").read_text(encoding="utf-8"))
    cfg["discord"].update(servidor="auto", canal_envios="manda-tu-polaroid", canal_revision="#Revision Polaroids", roles_admin_ids=[ADMIN_ROL])
    for k in ("servidor_id", "canal_envios_id", "canal_revision_id"): cfg["discord"].pop(k, None)
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
    avisos = [m["content"] for m in dc.canales["20"].values() if m["author"].get("bot")]
    assert any("aprobada como VIP" in t and "<@71>" in t for t in avisos), avisos
    assert any("fue aprobada!" in t for t in avisos), avisos
    assert not any("<@73>" in t and "aprobada" in t for t in avisos), "avisó una rechazada"
    assert not any("autor_id" in f for f in tt.d.fotos), "la foto publicada no debe guardar el ID del autor"
    conf = [m["content"] for m in dc.canales["30"].values() if m["author"].get("bot") and m["content"].startswith("<@" + ADMIN)]
    assert any("Listo" in t and "VIP" in t for t in conf) and any("rechazada" in t for t in conf), conf
    vipmsg = dc.canales["30"][ids[1]]["reacciones"]
    assert not any(u["id"] == BOT for u in vipmsg.get(APROBAR, []) + vipmsg.get(VIP, [])), "no quitó las reacciones del bot"
    print("2 ok: VIP + comunitaria aprobadas (con aviso al autor), rechazo aplicado, el no-admin no cuenta")

    # 3) avisos se borran después de 60 min
    tt, _ = pasada(ahora + 3700)
    assert not [m for m in dc.canales["20"].values() if m["author"].get("bot") and "recibimos" in m["content"]], "los avisos no se borraron"
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

    # 8) mudanza: invitan el bot a otro servidor con los mismos canales -> se va al nuevo
    dc.reloj_ms = (ahora + 16 * 86400) * 1000
    dc.usuario_manda("20", "400", "Vieja")
    tt, _ = pasada(ahora + 16 * 86400)
    dc.reacciona("30", [p for p in tt.d.estado["pendientes"] if p["autor"] == "Vieja"][0]["revision_id"], APROBAR, ADMIN)
    tt, _ = pasada(ahora + 16 * 86400 + 60)
    assert any(f["autor"] == "Vieja" for f in tt.d.fotos)
    dc.usuario_manda("20", "401", "Pendiente vieja")
    tt, _ = pasada(ahora + 16 * 86400 + 90)
    privado2 = [{"id": "11", "type": 0, "deny": str(1 << 10), "allow": "0"}]
    dc.servidores["11"] = {"name": "Otro", "entro": "2026-06-01T00:00:00",
                           "canales": [{"id": "21", "type": 0, "name": "manda-tu-polaroid"},
                                       {"id": "31", "type": 0, "name": "revision-polaroids", "permission_overwrites": privado2}]}
    dc.usuario_manda("21", "402", "Nueva")
    tt, _ = pasada(ahora + 16 * 86400 + 120)
    assert tt.servidor == "11" and tt.revision == "31", (tt.servidor, tt.revision)
    assert [p["autor"] for p in tt.d.estado["pendientes"]] == ["Nueva"], tt.d.estado["pendientes"]
    assert any(f["autor"] == "Vieja" for f in tt.d.fotos), "se perdió la foto del servidor anterior"
    # ❌ en el servidor viejo ya no se consulta (el bot pudo haber salido de ahí)
    dc.reacciona("30", [f for f in tt.d.fotos if f["autor"] == "Vieja"][0]["revision_id"], RECHAZAR, ADMIN)
    tt, _ = pasada(ahora + 16 * 86400 + 180)
    assert any(f["autor"] == "Vieja" for f in tt.d.fotos)
    print("8 ok: mudanza al servidor nuevo sin perder fotos; pendientes viejas descartadas")

    # 9) sin roles y canal de revisión público -> no arranca (cualquiera podría aprobar)
    import copy
    from tendedero.destino import ErrorDestino
    cfg2 = copy.deepcopy(cfg); cfg2["discord"]["roles_admin_ids"] = []
    dc.servidores["11"]["canales"][1]["permission_overwrites"] = []
    try:
        Tendedero(cfg2, dc, Datos(tmp), ahora=ahora); raise AssertionError("debía negarse")
    except ErrorDestino as e:
        assert "no es privado" in str(e)
    dc.servidores["11"]["canales"][1]["permission_overwrites"] = privado2
    Tendedero(cfg2, dc, Datos(tmp), ahora=ahora)   # privado y sin roles: vale
    print("9 ok: sin roles solo funciona si el canal de revisión es privado")

    # 10) invitan el bot a un servidor nuevo sin canales -> los crea (el de revisión privado) y se muda
    dc.servidores["12"] = {"name": "Nuevo", "entro": "2026-09-01T00:00:00", "canales": [{"id": "99", "type": 0, "name": "general"}]}
    tt, _ = pasada(ahora + 17 * 86400)
    nombres = {c["name"]: c for c in dc.servidores["12"]["canales"]}
    assert "manda-tu-polaroid" in nombres and "revision-polaroids" in nombres, nombres.keys()
    rev = nombres["revision-polaroids"]
    assert tt.servidor == "12" and tt.revision == rev["id"] and tt.destino["privado"]
    ids = {o["id"]: o for o in rev["permission_overwrites"]}
    assert int(ids["12"]["deny"]) & (1 << 10) and ids[BOT]["type"] == 1 and "admins12" in ids
    assert dc.canales.get(nombres["manda-tu-polaroid"]["id"]), "falta el mensaje de bienvenida"
    print("10 ok: servidor nuevo -> el bot crea los dos canales (revisión privada) y se muda")

    # 11) candado: alguien añade el bot (público) a SU servidor -> se ignora, no crea canales ni se muda
    dc.servidores["13"] = {"name": "Ajeno", "dueno": "666", "entro": "2026-12-01T00:00:00",
                           "canales": [{"id": "98", "type": 0, "name": "general"}]}
    tt, _ = pasada(ahora + 18 * 86400)
    assert tt.servidor == "12", tt.servidor
    assert len(dc.servidores["13"]["canales"]) == 1, "creó canales en un servidor ajeno"
    cfg["discord"]["salir_de_ajenos"] = True
    tt, _ = pasada(ahora + 18 * 86400 + 60)
    assert "13" not in dc.servidores, "no se salió del servidor ajeno"
    cfg["discord"]["salir_de_ajenos"] = False
    # y si el dueño de ese servidor está en duenos_permitidos, sí lo usa
    dc.servidores["14"] = {"name": "Amigo", "dueno": "777", "entro": "2026-12-02T00:00:00", "canales": []}
    cfg["discord"]["duenos_permitidos"] = ["777"]
    tt, _ = pasada(ahora + 18 * 86400 + 120)
    assert tt.servidor == "14" and len(dc.servidores["14"]["canales"]) == 2
    cfg["discord"]["duenos_permitidos"] = []
    # servidor de otro, pero el bot lo añadió el dueño del bot (es admin ahí) -> vale, y queda recordado
    dc.servidores["15"] = {"name": "Donde soy admin", "dueno": "888", "anadio": "500", "entro": "2026-12-03T00:00:00", "canales": []}
    tt, _ = pasada(ahora + 18 * 86400 + 180)
    assert tt.servidor == "15" and "15" in tt.d.estado["servidores_aprobados"]
    dc.servidores["15"]["anadio"] = None       # pasaron 45 días: el registro de auditoría ya no lo dice
    tt, _ = pasada(ahora + 18 * 86400 + 240)
    assert tt.servidor == "15", "olvidó que ese servidor ya estaba aprobado"
    print("11 ok: candado — servidores ajenos ignorados (o abandonados); los permitidos sí")

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
