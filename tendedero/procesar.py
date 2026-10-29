"""Una pasada del tendedero. La corre GitHub Actions cada 10 minutos.

1. Pasa las fotos nuevas del canal público al canal de revisión (y borra el original).
2. Lee las reacciones de los admins: ✅ aprobar · ⭐ VIP · ❌ rechazar / quitar.
3. Caduca las comunitarias viejas y las pendientes que nadie revisó.
4. Arma el atlas y el manifest y los deja en _site/ para publicarlos en GitHub Pages.
"""

import datetime as dt
import io
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import yaml

from . import atlas
from . import destino
from . import polaroid as pol
from .discord_api import Discord, DiscordError

RAIZ = Path(__file__).resolve().parent.parent
APROBAR, VIP, RECHAZAR = "✅", "⭐", "❌"
TIPOS_IMAGEN = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif")


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- datos
class Datos:
    def __init__(self, raiz=RAIZ):
        self.dir = Path(raiz) / "data"
        self.dir_fotos = self.dir / "fotos"
        self.dir_fotos.mkdir(parents=True, exist_ok=True)
        self.fotos = self._leer("fotos.json", [])
        self.estado = self._leer("estado.json", {})
        self.estado.setdefault("ultimo_envio_id", None)
        self.estado.setdefault("pendientes", [])
        self.estado.setdefault("avisos", [])
        self.estado.setdefault("ultimo_hash", "")
        self.estado.setdefault("ultimo_latido", "")
        self.estado.setdefault("servidor", "")
        self.estado.setdefault("canal_envios", "")
        self.estado.setdefault("canal_revision", "")

    def _leer(self, nombre, defecto):
        p = self.dir / nombre
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else defecto

    def guardar(self):
        (self.dir / "fotos.json").write_text(json.dumps(self.fotos, ensure_ascii=False, indent=1), encoding="utf-8")
        (self.dir / "estado.json").write_text(json.dumps(self.estado, ensure_ascii=False, indent=1), encoding="utf-8")

    def quitar_foto(self, f):
        self.fotos.remove(f)
        (self.dir_fotos / f["archivo"]).unlink(missing_ok=True)


def nombre_de(usuario, miembro=None):
    if miembro and miembro.get("nick"):
        return miembro["nick"]
    return usuario.get("global_name") or usuario.get("username") or "Anónimo"


def snowflake(ts):
    """ID de Discord que corresponde a un instante: los mensajes posteriores tienen IDs mayores."""
    return str((int(ts * 1000) - 1420070400000) << 22)


def es_imagen(adjunto):
    tipo = (adjunto.get("content_type") or "").lower()
    return tipo.startswith("image/") or adjunto.get("filename", "").lower().endswith(TIPOS_IMAGEN)


# ---------------------------------------------------------------- pasos
class Tendedero:
    def __init__(self, cfg, discord, datos, ahora=None):
        self.cfg, self.dc, self.d = cfg, discord, datos
        self.ahora = ahora if ahora is not None else time.time()
        self.textos = cfg["textos"]
        self.cambios = []
        c = cfg["discord"]
        aprobados = set(datos.estado.get("servidores_aprobados", []))
        d = destino.resolver(c, discord, log, aprobados)
        datos.estado["servidores_aprobados"] = sorted(aprobados)
        self.destino = d
        self.servidor, self.envios, self.revision = d["servidor"], d["envios"], d["revision"]
        self.roles_admin = {str(r) for r in c.get("roles_admin_ids", [])}
        if not self.roles_admin and not d["privado"]:
            raise destino.ErrorDestino(
                f"El canal #{d['nombre_revision']} no es privado y no hay roles de admin en config.yml: "
                "cualquiera podría aprobar fotos. Quítale 'Ver canal' a @everyone en ese canal.")
        self._cambio_de_servidor()

    def _cambio_de_servidor(self):
        """Si config.yml ahora apunta a otro servidor o a otros canales, se empieza limpio ahí
        sin perder las fotos ya publicadas."""
        e = self.d.estado
        # Datos de antes de esta versión: se asume que eran de los canales actuales
        for x in e["pendientes"] + self.d.fotos:
            x.setdefault("canal", e["canal_revision"] or self.revision)
        if e["canal_envios"] and e["canal_envios"] != self.envios:
            # Solo lo del último día (lo que mandaron mientras lo preparabas), no todo el historial del canal
            e["ultimo_envio_id"] = snowflake(self.ahora - 86400)
            e["avisos"] = []
            self.cambios.append("canal de envíos nuevo")
        if e["canal_revision"] and e["canal_revision"] != self.revision:
            if e["pendientes"]:
                self.cambios.append(f"{len(e['pendientes'])} pendientes del canal anterior descartadas")
            e["pendientes"] = []
        if e["servidor"] and e["servidor"] != self.servidor:
            self.cambios.append(f"ahora en el servidor {self.destino['nombre_servidor']}")
        e["servidor"], e["canal_envios"], e["canal_revision"] = self.servidor, self.envios, self.revision

    def es_admin(self, usuario_id):
        # Sin roles en config.yml: vale cualquiera que pueda ver el canal de revisión (que es privado).
        if not self.roles_admin:
            return True
        m = self.dc.miembro(self.servidor, usuario_id)
        return bool(m) and bool(self.roles_admin & set(m.get("roles", [])))

    def primer_admin(self, reaccionaron):
        yo = self.dc.quien_soy()["id"]
        for u in reaccionaron:
            if u["id"] != yo and not u.get("bot") and self.es_admin(u["id"]):
                return u
        return None

    # 1 ---------------------------------------------------------
    def pasar_envios(self):
        c = self.cfg["discord"]
        mensajes = self.dc.mensajes_despues(self.envios, self.d.estado["ultimo_envio_id"])
        yo = self.dc.quien_soy()["id"]
        for m in mensajes:
            self.d.estado["ultimo_envio_id"] = m["id"]
            if m["author"].get("bot") or m["author"]["id"] == yo:
                continue
            imagenes = [a for a in m.get("attachments", []) if es_imagen(a)]
            if not imagenes:
                continue
            miembro = self.dc.miembro(self.servidor, m["author"]["id"])
            autor = nombre_de(m["author"], miembro)
            for a in imagenes:
                datos = self.dc.descargar(a["url"])
                texto = self.textos["revision"].format(autor=pol.limpiar_nombre(autor))
                rev = self.dc.enviar(self.revision, texto, datos, a.get("filename") or "foto.jpg")
                for e in (APROBAR, VIP, RECHAZAR):
                    self.dc.reaccionar(self.revision, rev["id"], e)
                # autor_id solo mientras está pendiente, para avisarle al aprobarla; no se guarda en la foto publicada
                self.d.estado["pendientes"].append({"revision_id": rev["id"], "autor": autor, "recibida": int(self.ahora),
                                                    "canal": self.revision, "autor_id": m["author"]["id"]})
                self.cambios.append(f"recibida de {autor}")
            if c.get("avisar_recibida", True):
                aviso = self.dc.enviar(self.envios, self.textos["aviso_recibida"].format(mencion=f"<@{m['author']['id']}>"),
                                       menciones=[m["author"]["id"]])
                if aviso:
                    self.d.estado["avisos"].append({"id": aviso["id"], "borrar": int(self.ahora + 60 * c.get("minutos_aviso", 60))})
            if c.get("borrar_original", True):
                self.dc.borrar(self.envios, m["id"])

    def recuperar_huerfanas(self):
        """Si una pasada no pudo guardar su estado, sus fotos quedan en revisión sin que el
        tendedero lo sepa. Las busca por el texto de revisión y las vuelve a poner en pendientes."""
        # Solo la primera línea del texto: así se reconocen también los mensajes hechos con textos de antes
        primera = self.textos["revision"].split("\n")[0]
        patron = re.compile("^" + re.escape(primera).replace(re.escape("{autor}"), "(.+?)") + "(\n|$)", re.S)
        conocidas = {p["revision_id"] for p in self.d.estado["pendientes"]} | {f["revision_id"] for f in self.d.fotos}
        yo = self.dc.quien_soy()["id"]
        for m in self.dc.mensajes_recientes(self.revision):
            if m["id"] in conocidas or m["author"]["id"] != yo or not m.get("attachments"):
                continue
            coincide = patron.match(m.get("content", ""))
            if not coincide:
                continue
            recibida = ((int(m["id"]) >> 22) + 1420070400000) // 1000  # la fecha va dentro del ID de Discord
            self.d.estado["pendientes"].append({"revision_id": m["id"], "autor": coincide.group(1), "recibida": recibida,
                                                "canal": self.revision})
            self.cambios.append(f"recuperada la de {coincide.group(1)}")

    # 2 ---------------------------------------------------------
    def revisar_pendientes(self):
        for p in list(self.d.estado["pendientes"]):
            rechazo = self.primer_admin(self.dc.reacciones(self.revision, p["revision_id"], RECHAZAR))
            vip = self.primer_admin(self.dc.reacciones(self.revision, p["revision_id"], VIP))
            ok = self.primer_admin(self.dc.reacciones(self.revision, p["revision_id"], APROBAR))
            if rechazo:
                self.d.estado["pendientes"].remove(p)
                self.dc.editar(self.revision, p["revision_id"], self.textos["rechazada"].format(admin=nombre_de(rechazo)))
                self.confirmar_admin(p, rechazo, "confirma_rechazada", quitar=(APROBAR, VIP, RECHAZAR))
                self.cambios.append(f"rechazada de {p['autor']}")
            elif vip or ok:
                admin = vip or ok
                msg = self.dc.mensaje(self.revision, p["revision_id"])
                if not msg or not msg.get("attachments"):
                    self.d.estado["pendientes"].remove(p)
                    continue
                datos = self.dc.descargar(msg["attachments"][0]["url"])  # url firmada recién pedida
                img = pol.hacer_polaroid(datos, p["autor"], self.cfg["imagen"], vip=bool(vip))
                archivo = f"{uuid.uuid4().hex[:12]}.jpg"
                img.save(self.d.dir_fotos / archivo, "JPEG", quality=92)
                self.d.fotos.append({
                    "id": archivo[:-4], "archivo": archivo, "autor": pol.limpiar_nombre(p["autor"]),
                    "tipo": "vip" if vip else "comunidad", "aprobada": int(self.ahora),
                    "revision_id": p["revision_id"], "canal": self.revision,
                })
                self.d.estado["pendientes"].remove(p)
                texto = self.textos["aprobada_vip" if vip else "aprobada"].format(admin=nombre_de(admin))
                self.dc.editar(self.revision, p["revision_id"], texto + "\n(❌ para quitarla del tendedero)")
                self.avisar_aprobada(p, bool(vip))
                self.confirmar_admin(p, admin, "confirma_aprobada_vip" if vip else "confirma_aprobada", quitar=(APROBAR, VIP))
                self.cambios.append(f"aprobada {'VIP ' if vip else ''}de {p['autor']}")

    def confirmar_admin(self, p, admin, clave, quitar=()):
        """Le confirma al admin que su reacción se aplicó: responde al mensaje de revisión mencionándolo
        (le llega notificación) y quita las reacciones del bot que ya no sirven. La respuesta se borra sola."""
        try:
            for e in quitar:
                self.dc.quitar_mi_reaccion(self.revision, p["revision_id"], e)
        except DiscordError:
            pass
        plantilla = self.textos.get(clave)
        if not plantilla or not self.cfg["discord"].get("confirmar_admin", True):
            return
        try:
            r = self.dc.enviar(self.revision, plantilla.format(mencion=f"<@{admin['id']}>", autor=pol.limpiar_nombre(p["autor"])),
                               menciones=[admin["id"]], responde_a=p["revision_id"])
        except DiscordError as e:
            log(f"::warning::No pude confirmar al admin: {e}")
            return
        if r:
            minutos = self.cfg["discord"].get("minutos_aviso", 60)
            self.d.estado["avisos"].append({"id": r["id"], "canal": self.revision, "borrar": int(self.ahora + 60 * minutos)})

    def avisar_aprobada(self, p, vip):
        """Confirmación en el canal público para quien mandó la foto (se borra sola como los otros avisos)."""
        c = self.cfg["discord"]
        if not c.get("avisar_aprobada", True):
            return
        clave = "aviso_aprobada_vip" if vip else "aviso_aprobada"
        plantilla = self.textos.get(clave) or self.textos.get("aviso_aprobada")
        if not plantilla:
            return
        uid = p.get("autor_id")
        mencion = f"<@{uid}>" if uid else f"**{pol.limpiar_nombre(p['autor'])}**"
        try:
            aviso = self.dc.enviar(self.envios, plantilla.format(mencion=mencion, autor=pol.limpiar_nombre(p["autor"])),
                                   menciones=[uid] if uid else None)
        except DiscordError as e:
            log(f"::warning::No pude avisar de la foto aprobada: {e}")
            return
        if aviso:
            self.d.estado["avisos"].append({"id": aviso["id"], "borrar": int(self.ahora + 60 * c.get("minutos_aviso", 60))})

    # 3 ---------------------------------------------------------
    def revisar_publicadas(self):
        """Un admin puede quitar una foto ya publicada reaccionando ❌ en su mensaje de revisión."""
        for f in list(self.d.fotos):
            if f.get("canal", self.revision) != self.revision:
                continue   # se aprobó en otro servidor: ya no se puede quitar con ❌, solo caduca
            quita = self.primer_admin(self.dc.reacciones(self.revision, f["revision_id"], RECHAZAR))
            if quita:
                self.d.quitar_foto(f)
                self.dc.editar(self.revision, f["revision_id"], self.textos["quitada"].format(admin=nombre_de(quita)))
                self.confirmar_admin(f, quita, "confirma_quitada", quitar=(RECHAZAR,))
                self.cambios.append(f"quitada la de {f['autor']}")

    def caducar(self):
        t = self.cfg["tendedero"]
        limite = self.ahora - t["dias_caducidad"] * 86400
        com = sorted([f for f in self.d.fotos if f["tipo"] == "comunidad"], key=lambda f: f["aprobada"])
        sobran = max(0, len(com) - t["max_guardadas"])
        for i, f in enumerate(com):
            if f["aprobada"] < limite or i < sobran:
                self.d.quitar_foto(f)
                if f.get("canal", self.revision) == self.revision:
                    try:
                        self.dc.editar(self.revision, f["revision_id"], self.textos["caducada"])
                    except DiscordError:
                        pass
                self.cambios.append(f"caducó la de {f['autor']}")
        limite_p = self.ahora - t["dias_pendiente"] * 86400
        for p in list(self.d.estado["pendientes"]):
            if p["recibida"] < limite_p:
                self.d.estado["pendientes"].remove(p)
                try:
                    self.dc.editar(self.revision, p["revision_id"], self.textos["pendiente_caducada"])
                except DiscordError:
                    pass

    def borrar_avisos(self):
        for a in list(self.d.estado["avisos"]):
            if a["borrar"] <= self.ahora:
                try:
                    self.dc.borrar(a.get("canal", self.envios), a["id"])
                except DiscordError:
                    pass
                self.d.estado["avisos"].remove(a)

    # ---------------------------------------------------------
    def pasada(self, salida):
        self.pasar_envios()
        self.recuperar_huerfanas()
        self.revisar_pendientes()
        self.revisar_publicadas()
        self.caducar()
        self.borrar_avisos()
        version = atlas.construir_sitio(self.d.fotos, self.d.dir_fotos, self.cfg, self.ahora, salida)
        hoy = dt.datetime.fromtimestamp(self.ahora, dt.timezone.utc).strftime("%Y-%m-%d")
        publicar = version != self.d.estado["ultimo_hash"] or hoy != self.d.estado["ultimo_latido"]
        self.d.estado["ultimo_hash"] = version
        # Latido diario: un commit al día evita que GitHub apague la tarea programada por inactividad
        self.d.estado["ultimo_latido"] = hoy
        self.d.guardar()
        return publicar, version


def cargar_config(ruta=RAIZ / "config.yml"):
    cfg = yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))
    c = cfg["discord"]
    # Nombres de antes (con _id) siguen valiendo
    for viejo, nuevo in (("servidor_id", "servidor"), ("canal_envios_id", "canal_envios"), ("canal_revision_id", "canal_revision")):
        if viejo in c and nuevo not in c:
            c[nuevo] = c.pop(viejo)
    c["servidor"] = str(c.get("servidor") or "auto").strip()
    if set(c["servidor"]) == {"0"}:
        c["servidor"] = "auto"
    for k in ("canal_envios", "canal_revision"):
        v = str(c.get(k) or "").strip()
        if not v or set(v) == {"0"}:
            raise SystemExit(f"Falta poner '{k}' en config.yml (el nombre del canal, por ejemplo manda-tu-polaroid).")
        c[k] = v
    c["roles_admin_ids"] = [str(r) for r in (c.get("roles_admin_ids") or []) if str(r).strip("0 ")]
    return cfg


def main():
    salida = os.environ.get("GITHUB_OUTPUT")
    try:
        cfg = cargar_config()
    except SystemExit as e:
        # Sin configurar todavía: aviso amarillo en vez de fallar cada 10 minutos (y llenar el correo de avisos)
        log(f"::warning::{e}")
        if salida:
            with open(salida, "a") as f:
                f.write("publicar=false\n")
        return
    try:
        t = Tendedero(cfg, Discord(os.environ.get("DISCORD_TOKEN", "")), Datos())
        publicar, version = t.pasada(RAIZ / "_site")
    except DiscordError as e:
        log(f"::error::{e}")
        sys.exit(1)
    d = t.destino
    log(f"::notice::Servidor '{d['nombre_servidor']}' · envíos #{d['nombre_envios']} · revisión #{d['nombre_revision']}"
        f"{' (privado)' if d['privado'] else ''} · cambios: {', '.join(t.cambios) or 'ninguno'}")
    log(f"::notice::Para llevar el tendedero a otro servidor, invita el bot con este enlace (crea los canales solo): "
        f"{destino.enlace_invitacion(t.dc.quien_soy()['id'])}")
    log("Cambios:", ", ".join(t.cambios) or "ninguno", "| versión", version, "| publicar:", publicar)
    if salida:
        with open(salida, "a") as f:
            f.write(f"publicar={'true' if publicar else 'false'}\n")


if __name__ == "__main__":
    main()
