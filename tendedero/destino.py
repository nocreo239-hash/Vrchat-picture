"""Encuentra en qué servidor y canales trabaja el bot.

En config.yml los canales se pueden poner por NOMBRE (lo normal) o por ID. Con el servidor en "auto",
el bot busca esos canales en todos los servidores donde está. Así, para cambiar el tendedero de
servidor basta con invitar el bot al servidor nuevo y crear ahí los dos canales con esos nombres.
"""

from .discord_api import DiscordError

VER_CANAL = 1 << 10          # permiso "Ver canal"
TIPOS_TEXTO = (0, 5)         # canal de texto y de anuncios


class ErrorDestino(DiscordError):
    pass


def normalizar(nombre):
    """'# Manda tu Polaroid' -> 'manda-tu-polaroid' (como Discord guarda los nombres de canal)."""
    n = str(nombre).strip().lstrip("#").strip().lower()
    return "-".join(n.split())


def _buscar(canales, valor):
    v = str(valor).strip()
    for ch in canales:
        if ch.get("type") in TIPOS_TEXTO and (ch["id"] == v or ch.get("name") == normalizar(v)):
            return ch
    return None


def es_privado(canal, servidor_id):
    """Privado = @everyone (su rol tiene el mismo ID que el servidor) no puede ver el canal."""
    for o in canal.get("permission_overwrites", []):
        if str(o.get("id")) == str(servidor_id) and int(o.get("deny", 0)) & VER_CANAL:
            return True
    return False


def resolver(cfg_discord, dc, log=print):
    """Devuelve un dict con servidor, canales (ID y nombre) y si el canal de revisión es privado."""
    serv = str(cfg_discord.get("servidor", "auto")).strip()
    env, rev = cfg_discord["canal_envios"], cfg_discord["canal_revision"]

    if serv.isdigit():
        candidatos = [{"id": serv, "name": serv}]
    else:
        candidatos = dc.mis_servidores()
        if not candidatos:
            raise ErrorDestino("El bot no está en ningún servidor. Invítalo con el enlace de OAuth2 (paso 1 del LEEME).")

    encontrados, vistos = [], []
    for g in candidatos:
        chans = dc.canales_de(g["id"])
        a, b = _buscar(chans, env), _buscar(chans, rev)
        if a and b:
            encontrados.append((g, a, b))
        nombres = [c.get("name") for c in chans if c.get("type") in TIPOS_TEXTO]
        vistos.append(f"{g.get('name', g['id'])}: " + ", ".join("#" + n for n in nombres[:25]))

    if not encontrados:
        donde = "ese servidor" if serv.isdigit() else f"ninguno de los {len(candidatos)} servidores donde está el bot"
        raise ErrorDestino(f"No encontré los canales '{env}' y '{rev}' en {donde}. "
                           "Crea los dos canales con esos nombres (o cambia los nombres en config.yml). "
                           "Canales que veo -> " + " | ".join(vistos))

    elegido = encontrados[0]
    if len(encontrados) > 1:
        # Varios servidores tienen los dos canales: gana aquel al que invitaste el bot más recientemente.
        # Así, para mudar el tendedero basta con invitar el bot al servidor nuevo.
        yo = dc.quien_soy()["id"]

        def entrada(e):
            m = dc.miembro(e[0]["id"], yo) or {}
            return m.get("joined_at") or ""
        elegido = max(encontrados, key=entrada)
        nombres = ", ".join(e[0].get("name", e[0]["id"]) for e in encontrados)
        log(f"::warning::Los canales existen en varios servidores ({nombres}). Uso '{elegido[0].get('name')}', "
            "el último al que invitaste el bot. Para fijar uno, pon su ID en 'servidor' en config.yml.")

    g, a, b = elegido
    return {"servidor": g["id"], "nombre_servidor": g.get("name", g["id"]),
            "envios": a["id"], "nombre_envios": a.get("name", a["id"]),
            "revision": b["id"], "nombre_revision": b.get("name", b["id"]),
            "privado": es_privado(b, g["id"])}
