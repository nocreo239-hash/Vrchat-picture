"""Avisa en Discord cuando se abre una instancia de tu mundo.

- Instancias de GRUPO: el registro del grupo dice quién la abrió  ->  "🟢 Fulano abrió una instancia".
- Instancias PÚBLICAS: VRChat no dice quién las abrió; avisa que hay una nueva y cuánta gente tiene.
- Las Friends / Invite de otras personas son privadas: la API no las enseña.

Lo corre el mismo workflow del tendedero, en cada pasada. Usa una cuenta secundaria de VRChat
(secretos VRC_USUARIO, VRC_CONTRASENA y VRC_TOTP) que esté en el grupo con permiso de ver el registro.
"""

import base64
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import yaml

from tendedero import destino
from tendedero.discord_api import Discord, DiscordError
from .vrchat_api import VRChat, VRChatError

RAIZ = Path(__file__).resolve().parent.parent
ESTADO = RAIZ / "data" / "avisos_estado.json"
SESION = RAIZ / "data" / "vrc_sesion.enc"
MAX_RECUERDA = 300


def log(*a):
    print(*a, flush=True)


def huella(texto):
    """Lo que se guarda en el repositorio (público): una huella, nunca nombres ni IDs de instancia."""
    return hashlib.sha256(str(texto).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- sesión cifrada
def _fernet(usuario, contrasena, totp):
    from cryptography.fernet import Fernet
    clave = hashlib.sha256(f"cuervos|{usuario}|{contrasena}|{totp}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(clave))


def leer_sesion(f):
    if not SESION.exists():
        log("::notice::No hay sesión guardada todavía.")
        return {}
    try:
        return json.loads(f.decrypt(SESION.read_bytes()))
    except Exception as e:
        log(f"::notice::No pude descifrar la sesión guardada ({type(e).__name__}); inicio sesión de nuevo.")
        return {}


def guardar_sesion(f, cookies):
    SESION.parent.mkdir(parents=True, exist_ok=True)
    SESION.write_bytes(f.encrypt(json.dumps(cookies).encode()))


# ---------------------------------------------------------------- texto
TIPOS = {"public": "de grupo (pública)", "plus": "Grupo+", "members": "solo miembros del grupo"}


def describir(ubicacion):
    """'wrld_x:12345~group(grp_y)~groupAccessType(plus)~region(us)' -> 'Grupo+ · región US'."""
    u = str(ubicacion or "")
    partes = []
    m = re.search(r"groupAccessType\((\w+)\)", u)
    if m:
        partes.append(TIPOS.get(m.group(1), m.group(1)))
    m = re.search(r"region\((\w+)\)", u)
    if m:
        partes.append("región " + m.group(1).upper())
    return " · ".join(partes)


def ubicacion_de(entrada):
    for v in (entrada.get("targetId"), (entrada.get("data") or {}).get("location"),
              (entrada.get("data") or {}).get("instanceId")):
        if isinstance(v, str) and v.startswith("wrld_"):
            return v
    return ""


def es_de_mi_mundo(entrada, mundo_id):
    if not mundo_id:
        return True
    texto = json.dumps(entrada)
    return mundo_id in texto or "wrld_" not in texto   # si no dice el mundo, mejor avisar


# ---------------------------------------------------------------- Discord
def canal_avisos(dc, cfg, log=log):
    """Busca (o crea, privado como el de revisión) el canal de avisos en el servidor del tendedero."""
    d = destino.resolver(cfg["discord"], dc, log)
    nombre = destino.normalizar(cfg["avisos"].get("canal", "avisos-instancias"))
    chans = dc.canales_de(d["servidor"])
    c = destino._buscar(chans, nombre)
    if c:
        return c["id"]
    yo = dc.quien_soy()["id"]
    permitidos = {str(r) for r in cfg["discord"].get("roles_admin_ids", [])}
    for r in dc.roles(d["servidor"]):
        if int(r.get("permissions", 0)) & (destino.ADMINISTRADOR | destino.GESTIONAR_SERVIDOR) and str(r["id"]) != str(d["servidor"]):
            permitidos.add(str(r["id"]))
    ow = [{"id": str(d["servidor"]), "type": 0, "allow": "0", "deny": str(destino.VER_CANAL)},
          {"id": str(yo), "type": 1, "allow": str(destino.PERMISOS_BOT), "deny": "0"}]
    ow += [{"id": r, "type": 0, "allow": str(destino.VER_CANAL), "deny": "0"} for r in sorted(permitidos)]
    c = dc.crear_canal(d["servidor"], nombre, "Avisos del bot: quién abre instancias de Cuervos Club.", ow)
    dc.enviar(c["id"], "🔔 Aquí aviso cuando alguien abre una instancia de **Cuervos Club**.\n"
                       "Las de grupo dicen quién la abrió; las públicas, cuánta gente tienen. "
                       "Las Friends/Invite de otras personas no se pueden ver.")
    log(f"::notice::Creé #{nombre} (privado) en '{d['nombre_servidor']}'.")
    return c["id"]


# ---------------------------------------------------------------- pasada
def pasada(cfg, vr, dc, estado, ahora=None, log=log):
    ahora = ahora or dt.datetime.now(dt.timezone.utc)
    a = cfg["avisos"]
    mundo_id = str(a.get("mundo_id") or "").strip()
    primera = not estado.get("iniciado")
    vistos = set(estado.get("vistos", []))
    publicas_antes = set(estado.get("publicas", []))
    mensajes = []

    # --- grupo
    grupo_id = str(a.get("grupo_id") or "").strip()
    if not grupo_id:
        busca = str(a.get("grupo_nombre") or "cuervos").lower()
        for g in vr.grupos_mios():
            if busca in str(g.get("name", "")).lower():
                grupo_id = g.get("groupId") or g.get("id")
                log(f"::notice::Grupo encontrado: {g.get('name')} ({grupo_id}). Puedes fijarlo en avisos.grupo_id.")
                break
    if grupo_id:
        try:
            entradas = vr.registro_grupo(grupo_id)
        except VRChatError as e:
            entradas = []
            log(f"::warning::No pude leer el registro del grupo (¿la cuenta del bot tiene permiso de ver el registro?): {e}")
        for e in sorted(entradas, key=lambda x: x.get("created_at", "")):
            if "instance.create" not in str(e.get("eventType", "")):
                continue
            h = huella(e.get("id"))
            if h in vistos:
                continue
            vistos.add(h)
            if primera or not es_de_mi_mundo(e, mundo_id):
                continue
            try:
                cuando = dt.datetime.fromisoformat(str(e["created_at"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                cuando = ahora
            if ahora - cuando > dt.timedelta(hours=3):
                continue   # muy viejo (p. ej. la primera vez que lee el registro)
            tipo = describir(ubicacion_de(e))
            mensajes.append(f"🟢 **{e.get('actorDisplayName') or 'Alguien'}** abrió una instancia "
                            f"{tipo or 'de grupo'} · <t:{int(cuando.timestamp())}:t>")
    else:
        log("::warning::La cuenta del bot no está en ningún grupo que se llame como avisos.grupo_nombre.")

    # --- públicas del mundo
    resumen = ""
    publicas_ahora = set()
    if mundo_id:
        m = vr.mundo(mundo_id)
        for inst in m.get("instances") or []:
            iid, gente = (inst[0], inst[1]) if isinstance(inst, list) else (inst.get("id"), inst.get("n_users"))
            if "~" in str(iid) and "group(" not in str(iid):
                continue   # solo las públicas de verdad (sin ~)
            h = huella(iid)
            publicas_ahora.add(h)
            if h not in publicas_antes and not primera:
                mensajes.append(f"🌐 Se abrió una instancia **pública** · {gente} {'persona' if gente == 1 else 'personas'}")
        if m:
            resumen = (f"👥 Ahora en Cuervos Club: **{m.get('occupants', 0)}** "
                       f"({m.get('publicOccupants', 0)} en públicas, {m.get('privateOccupants', 0)} en privadas o de grupo)")

    if mensajes:
        canal = canal_avisos(dc, cfg, log)
        texto = "\n".join(mensajes + ([resumen] if resumen else []))
        dc.enviar(canal, texto)
        log(f"::notice::Avisos enviados: {len(mensajes)}")
    elif primera:
        canal_avisos(dc, cfg, log)
        log("::notice::Primera pasada de avisos: marqué lo que ya existía, a partir de ahora aviso lo nuevo.")

    estado["iniciado"] = True
    estado["vistos"] = sorted(vistos)[-MAX_RECUERDA:] if len(vistos) > MAX_RECUERDA else sorted(vistos)
    estado["publicas"] = sorted(publicas_ahora)
    return mensajes


def main():
    cfg = yaml.safe_load((RAIZ / "config.yml").read_text(encoding="utf-8"))
    a = cfg.get("avisos") or {}
    if not a.get("activado", True):
        return
    usuario = os.environ.get("VRC_USUARIO", "").strip()
    contrasena = os.environ.get("VRC_CONTRASENA", "")
    secreto = os.environ.get("VRC_TOTP", "").strip()
    faltan = [n for n, v in (("VRC_USUARIO", usuario), ("VRC_CONTRASENA", contrasena), ("VRC_TOTP", secreto)) if not v]
    if not (usuario and contrasena):
        log(f"::notice::Avisos de instancias apagados: faltan los secretos {', '.join(faltan)} "
            "(Settings → Secrets and variables → Actions → pestaña Secrets → Repository secrets).")
        return
    if faltan:
        log(f"::notice::Falta el secreto {', '.join(faltan)}; si la cuenta tiene 2FA no podrá entrar.")
    cfg["avisos"] = a
    f = _fernet(usuario, contrasena, secreto)
    estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}
    vr = VRChat(usuario, contrasena, secreto, leer_sesion(f))
    try:
        nueva = vr.entrar(log)
        if nueva:
            log("::notice::Sesión de VRChat iniciada (se reutiliza en las próximas pasadas).")
        guardar_sesion(f, vr.cookies)
        pasada(cfg, vr, Discord(os.environ.get("DISCORD_TOKEN", "")), estado)
    except (VRChatError, DiscordError) as e:
        log(f"::warning::Avisos de instancias: {e}")
    finally:
        log(f"::notice::Cookies recibidas en la pasada: {' '.join(vr.vistas) or 'ninguna'} · "
            f"al final: {vr._resumen_cookies()}")
        try:
            ok = bool((vr._pedir("GET", "/auth/user") or {}).get("id"))
        except VRChatError as e:
            ok = f"no ({str(e)[:80]})"
        log(f"::notice::¿La sesión sigue viva al terminar? {ok}")
        guardar_sesion(f, vr.cookies)
        ESTADO.write_text(json.dumps(estado, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
