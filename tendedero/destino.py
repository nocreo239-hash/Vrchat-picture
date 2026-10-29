"""Encuentra en qué servidor y canales trabaja el bot.

En config.yml los canales se pueden poner por NOMBRE (lo normal) o por ID. Con el servidor en "auto",
el bot busca esos canales en todos los servidores donde está. Así, para cambiar el tendedero de
servidor basta con invitar el bot al servidor nuevo y crear ahí los dos canales con esos nombres.
"""

from .discord_api import DiscordError

VER_CANAL = 1 << 10          # permiso "Ver canal"
TIPOS_TEXTO = (0, 5)         # canal de texto y de anuncios
ADMINISTRADOR, GESTIONAR_SERVIDOR = 1 << 3, 1 << 5
# Lo que el bot necesita dentro del canal privado: ver, escribir, adjuntar, reaccionar, historial, gestionar mensajes
PERMISOS_BOT = (1 << 10) | (1 << 11) | (1 << 15) | (1 << 6) | (1 << 16) | (1 << 13)
# Para el enlace de invitación: lo de arriba + Gestionar canales (para crear los dos canales solo)
# + Ver registro de auditoría (para saber quién lo añadió a un servidor que no es tuyo)
PERMISOS_INVITACION = PERMISOS_BOT | (1 << 4) | (1 << 7)


def enlace_invitacion(app_id):
    return f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot&permissions={PERMISOS_INVITACION}"


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


def es_privado(canal, servidor_id, permisos_everyone=None):
    """Privado = @everyone (su rol tiene el mismo ID que el servidor) no puede ver el canal:
    o el canal se lo quita, o el servidor no se lo da y el canal no se lo devuelve."""
    for o in canal.get("permission_overwrites", []):
        if str(o.get("id")) == str(servidor_id):
            if int(o.get("deny", 0)) & VER_CANAL:
                return True
            if int(o.get("allow", 0)) & VER_CANAL:
                return False
    return permisos_everyone is not None and not (int(permisos_everyone) & VER_CANAL)


def resolver(cfg_discord, dc, log=print, aprobados=None):
    """Devuelve un dict con servidor, canales (ID y nombre) y si el canal de revisión es privado."""
    serv = str(cfg_discord.get("servidor", "auto")).strip()
    env, rev = cfg_discord["canal_envios"], cfg_discord["canal_revision"]

    if serv.isdigit():
        candidatos = [{"id": serv, "name": serv}]
    else:
        candidatos = dc.mis_servidores()
        if not candidatos:
            raise ErrorDestino("El bot no está en ningún servidor. Invítalo con el enlace de OAuth2 (paso 1 del LEEME).")
        candidatos = solo_permitidos(dc, candidatos, cfg_discord, log, aprobados)
        if not candidatos:
            raise ErrorDestino("El bot solo está en servidores de otras personas. Invítalo a un servidor tuyo "
                               "(o añade al dueño en 'duenos_permitidos' de config.yml).")

    yo = dc.quien_soy()["id"]

    def entrada(g):
        m = dc.miembro(g["id"], yo) or {}
        return m.get("joined_at") or ""

    encontrados, vistos, por_id = [], [], {}
    for g in candidatos:
        chans = dc.canales_de(g["id"])
        por_id[g["id"]] = chans
        a, b = _buscar(chans, env), _buscar(chans, rev)
        if a and b:
            encontrados.append((g, a, b))
        nombres = [c.get("name") for c in chans if c.get("type") in TIPOS_TEXTO]
        vistos.append(f"{g.get('name', g['id'])}: " + ", ".join("#" + n for n in nombres[:25]))

    # El último servidor al que invitaste el bot, si le faltan los canales, los crea el bot (si puede)
    if cfg_discord.get("crear_canales", True):
        nuevo = max(candidatos, key=entrada) if len(candidatos) > 1 else candidatos[0]
        if not any(e[0]["id"] == nuevo["id"] for e in encontrados):
            hecho = crear_canales(dc, nuevo, por_id[nuevo["id"]], env, rev, cfg_discord, yo, log)
            if hecho:
                encontrados.append((nuevo,) + hecho)

    if not encontrados:
        donde = "ese servidor" if serv.isdigit() else f"ninguno de los {len(candidatos)} servidores donde está el bot"
        raise ErrorDestino(f"No encontré los canales '{env}' y '{rev}' en {donde}. "
                           "Crea los dos canales con esos nombres (o cambia los nombres en config.yml). "
                           "Canales que veo -> " + " | ".join(vistos))

    elegido = encontrados[0]
    if len(encontrados) > 1:
        # Varios servidores tienen los dos canales: gana aquel al que invitaste el bot más recientemente.
        # Así, para mudar el tendedero basta con invitar el bot al servidor nuevo.
        elegido = max(encontrados, key=lambda e: entrada(e[0]))
        nombres = ", ".join(e[0].get("name", e[0]["id"]) for e in encontrados)
        log(f"::warning::Los canales existen en varios servidores ({nombres}). Uso '{elegido[0].get('name')}', "
            "el último al que invitaste el bot. Para fijar uno, pon su ID en 'servidor' en config.yml.")

    g, a, b = elegido
    return {"servidor": g["id"], "nombre_servidor": g.get("name", g["id"]),
            "envios": a["id"], "nombre_envios": a.get("name", a["id"]),
            "revision": b["id"], "nombre_revision": b.get("name", b["id"]),
            "privado": es_privado(b, g["id"], _permisos_everyone(dc, g["id"]))}


def _permisos_everyone(dc, servidor_id):
    for r in dc.roles(servidor_id):
        if str(r.get("id")) == str(servidor_id):
            return r.get("permissions", "0")
    return None


def crear_canales(dc, g, chans, env, rev, cfg_discord, yo, log):
    """Crea en el servidor g los canales que falten. Devuelve (canal_envios, canal_revision) o None."""
    a, b = _buscar(chans, env), _buscar(chans, rev)
    for v in (env, rev):
        if str(v).strip().isdigit() and not _buscar(chans, v):
            log(f"::warning::En config.yml el canal '{v}' es un ID, así que no puedo crearlo en '{g.get('name')}'. "
                "Pon nombres de canal para que el bot los cree solo.")
            return None
    try:
        if a is None:
            a = dc.crear_canal(g["id"], normalizar(env), "Manda aquí tu foto para el tendedero del mundo de VRChat. "
                               "Un admin la revisa y en unos minutos aparece colgada con tu nombre.")
            dc.enviar(a["id"], "📸 **Manda aquí tu foto** y aparecerá en el tendedero del mundo, con tu nombre.\n"
                               "Los admins la revisan antes de colgarla. Una foto por mensaje.")
            log(f"::notice::Creé #{a.get('name')} en '{g.get('name')}'.")
        if b is None:
            # Privado: nadie lo ve salvo el bot y los roles de administrador (y los de roles_admin_ids)
            permitidos = {str(r) for r in cfg_discord.get("roles_admin_ids", [])}
            for r in dc.roles(g["id"]):
                if int(r.get("permissions", 0)) & (ADMINISTRADOR | GESTIONAR_SERVIDOR) and str(r["id"]) != str(g["id"]):
                    permitidos.add(str(r["id"]))
            ow = [{"id": str(g["id"]), "type": 0, "allow": "0", "deny": str(VER_CANAL)},
                  {"id": str(yo), "type": 1, "allow": str(PERMISOS_BOT), "deny": "0"}]
            ow += [{"id": r, "type": 0, "allow": str(VER_CANAL), "deny": "0"} for r in sorted(permitidos)]
            b = dc.crear_canal(g["id"], normalizar(rev), "Revisión del tendedero: ✅ aprobar · ⭐ VIP · ❌ rechazar. "
                               "Quien vea este canal puede aprobar fotos.", ow)
            dc.enviar(b["id"], "Aquí llegan las fotos para revisar. Reacciona **✅** para aprobar, **⭐** para ponerla "
                               "como VIP o **❌** para rechazarla (o para quitar una ya colgada).\n"
                               "Solo los administradores ven este canal; si quieres que otros revisen, dales permiso de "
                               "*Ver canal* aquí.")
            log(f"::notice::Creé #{b.get('name')} (privado) en '{g.get('name')}'.")
        return a, b
    except DiscordError as e:
        log(f"::warning::No pude crear los canales en '{g.get('name')}': {e}. Invita el bot con permiso de "
            f"Gestionar canales: {enlace_invitacion(yo)}")
        return None


def duenos(dc, cfg_discord):
    """IDs de usuario cuyos servidores puede usar el tendedero: el dueño de la app del bot (o su equipo)
    y los que pongas en duenos_permitidos."""
    ids = {str(x).strip() for x in (cfg_discord.get("duenos_permitidos") or []) if str(x).strip("0 ")}
    app = dc.aplicacion()
    if app.get("owner", {}).get("id"):
        ids.add(str(app["owner"]["id"]))
    for m in (app.get("team") or {}).get("members", []):
        if m.get("user", {}).get("id"):
            ids.add(str(m["user"]["id"]))
    return ids


def solo_permitidos(dc, candidatos, cfg_discord, log, aprobados=None):
    """Candado: con el bot público cualquiera puede añadirlo a su servidor. Solo valen los servidores
    cuyo dueño eres tú, o a los que TÚ añadiste el bot (por ejemplo uno donde eres admin). Los demás se
    ignoran (o el bot se sale, con salir_de_ajenos: true), así nadie se lleva tu tendedero.
    `aprobados` (un set) recuerda los servidores ya verificados: el registro de auditoría solo dura 45 días."""
    aprobados = aprobados if aprobados is not None else set()
    permitidos = duenos(dc, cfg_discord)
    if not permitidos:
        log("::warning::No pude saber quién es el dueño del bot; no aplico el candado de servidores.")
        return candidatos
    yo = dc.quien_soy()["id"]
    buenos = []
    for g in candidatos:
        if g["id"] in aprobados:
            buenos.append(g)
            continue
        info = dc.servidor(g["id"]) or {}
        if str(info.get("owner_id")) in permitidos:
            aprobados.add(g["id"])
            buenos.append(g)
            continue
        try:
            quien = dc.quien_me_anadio(g["id"], yo)
        except DiscordError:
            quien = None   # sin permiso de ver el registro de auditoría
        if quien in permitidos:
            aprobados.add(g["id"])
            buenos.append(g)
            log(f"::notice::'{g.get('name')}' no es tuyo, pero lo añadiste tú: lo uso.")
            continue
        if cfg_discord.get("salir_de_ajenos"):
            try:
                dc.salir_de(g["id"])
                log(f"::warning::Me salí de '{g.get('name')}': su dueño no está permitido.")
            except DiscordError as e:
                log(f"::warning::No pude salir de '{g.get('name')}': {e}")
        else:
            log(f"::warning::Ignoro '{g.get('name')}': ni su dueño ni quien añadió el bot eres tú (o alguien de "
                "'duenos_permitidos'). Si lo añadiste tú, invítalo con el enlace que da permiso de ver el registro "
                "de auditoría.")
    return buenos
