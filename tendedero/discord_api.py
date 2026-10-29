"""Cliente mínimo de la API REST de Discord (sin librerías externas).

Solo lo que usa el tendedero: leer mensajes, reenviar con imagen, reacciones, editar y borrar.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = "https://discord.com/api/v10"


class DiscordError(Exception):
    pass


class Discord:
    def __init__(self, token):
        if not token:
            raise DiscordError("Falta el secreto DISCORD_TOKEN (Settings > Secrets and variables > Actions).")
        self.token = token
        self._miembros = {}
        self.yo = None

    # ------------------------------------------------------------ base
    def _pedir(self, metodo, ruta, cuerpo=None, tipo=None, intentos=5):
        url = API + ruta
        for _ in range(intentos):
            req = urllib.request.Request(url, data=cuerpo, method=metodo)
            req.add_header("Authorization", f"Bot {self.token}")
            req.add_header("User-Agent", "TendederoPolaroid (https://github.com, 1.0)")
            if tipo:
                req.add_header("Content-Type", tipo)
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    datos = r.read()
                    return json.loads(datos) if datos else None
            except urllib.error.HTTPError as e:
                texto = e.read().decode("utf-8", "replace")
                if e.code == 429:  # límite de velocidad: esperar lo que pide Discord
                    try:
                        espera = float(json.loads(texto).get("retry_after", 1))
                    except ValueError:
                        espera = 1.0
                    time.sleep(espera + 0.1)
                    continue
                if e.code == 404:
                    return None
                if e.code == 403:
                    raise DiscordError(f"Discord negó permiso en {metodo} {ruta}. Revisa los permisos del bot en ese canal. {texto[:200]}")
                if e.code == 401:
                    raise DiscordError("El token del bot no es válido (DISCORD_TOKEN).")
                raise DiscordError(f"Discord {e.code} en {metodo} {ruta}: {texto[:300]}")
        raise DiscordError(f"Discord siguió limitando la velocidad en {ruta}")

    def _json(self, metodo, ruta, datos):
        return self._pedir(metodo, ruta, json.dumps(datos).encode(), "application/json")

    # ------------------------------------------------------------ lectura
    def quien_soy(self):
        if self.yo is None:
            self.yo = self._pedir("GET", "/users/@me")
        return self.yo

    def mis_servidores(self):
        """Servidores donde está el bot."""
        return self._pedir("GET", "/users/@me/guilds?limit=200") or []

    def canales_de(self, servidor):
        return self._pedir("GET", f"/guilds/{servidor}/channels") or []

    def crear_canal(self, servidor, nombre, tema="", overwrites=None):
        datos = {"name": nombre, "type": 0, "topic": tema, "permission_overwrites": overwrites or []}
        return self._json("POST", f"/guilds/{servidor}/channels", datos)

    def aplicacion(self):
        """La app del bot: trae quién es su dueño (o los miembros de su equipo)."""
        return self._pedir("GET", "/oauth2/applications/@me") or {}

    def quien_me_anadio(self, servidor, bot_id):
        """ID de quien añadió el bot al servidor, según el registro de auditoría (dura 45 días)."""
        q = urllib.parse.urlencode({"action_type": 28, "limit": 50})   # 28 = BOT_ADD
        datos = self._pedir("GET", f"/guilds/{servidor}/audit-logs?{q}") or {}
        for e in datos.get("audit_log_entries", []):
            if str(e.get("target_id")) == str(bot_id):
                return str(e.get("user_id"))
        return None

    def salir_de(self, servidor):
        self._pedir("DELETE", f"/users/@me/guilds/{servidor}")

    def roles(self, servidor):
        return self._pedir("GET", f"/guilds/{servidor}/roles") or []

    def servidor(self, servidor_id):
        return self._pedir("GET", f"/guilds/{servidor_id}")

    def mensajes_despues(self, canal, despues_de=None):
        """Todos los mensajes posteriores a `despues_de`, del más viejo al más nuevo."""
        todos, desde = [], despues_de or "0"
        while True:
            q = urllib.parse.urlencode({"after": desde, "limit": 100})
            lote = self._pedir("GET", f"/channels/{canal}/messages?{q}") or []
            if not lote:
                break
            lote.sort(key=lambda m: int(m["id"]))
            todos.extend(lote)
            desde = lote[-1]["id"]
            if len(lote) < 100:
                break
        return todos

    def mensajes_recientes(self, canal, limite=100):
        """Los últimos `limite` mensajes del canal (del más nuevo al más viejo)."""
        return self._pedir("GET", f"/channels/{canal}/messages?limit={limite}") or []

    def mensaje(self, canal, mensaje_id):
        return self._pedir("GET", f"/channels/{canal}/messages/{mensaje_id}")

    def reacciones(self, canal, mensaje_id, emoji):
        e = urllib.parse.quote(emoji)
        return self._pedir("GET", f"/channels/{canal}/messages/{mensaje_id}/reactions/{e}?limit=100") or []

    def miembro(self, servidor, usuario):
        clave = (str(servidor), str(usuario))   # el mismo usuario es otro miembro en cada servidor
        if clave not in self._miembros:
            self._miembros[clave] = self._pedir("GET", f"/guilds/{servidor}/members/{usuario}")
        return self._miembros[clave]

    def descargar(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": "TendederoPolaroid (1.0)"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()

    # ------------------------------------------------------------ escritura
    def enviar(self, canal, texto, archivo=None, nombre_archivo="foto.jpg", menciones=None):
        datos = {"content": texto, "allowed_mentions": {"parse": [], "users": menciones or []}}
        if archivo is None:
            return self._json("POST", f"/channels/{canal}/messages", datos)
        limite = uuid.uuid4().hex
        partes = [
            f"--{limite}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
            f"Content-Type: application/json\r\n\r\n{json.dumps(datos)}\r\n".encode(),
            f"--{limite}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"{nombre_archivo}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n".encode() + archivo + b"\r\n",
            f"--{limite}--\r\n".encode(),
        ]
        return self._pedir("POST", f"/channels/{canal}/messages", b"".join(partes),
                           f"multipart/form-data; boundary={limite}")

    def reaccionar(self, canal, mensaje_id, emoji):
        e = urllib.parse.quote(emoji)
        self._pedir("PUT", f"/channels/{canal}/messages/{mensaje_id}/reactions/{e}/@me")
        time.sleep(0.3)  # Discord limita las reacciones a unas 4 por segundo

    def editar(self, canal, mensaje_id, texto):
        return self._json("PATCH", f"/channels/{canal}/messages/{mensaje_id}",
                          {"content": texto, "allowed_mentions": {"parse": []}})

    def borrar(self, canal, mensaje_id):
        self._pedir("DELETE", f"/channels/{canal}/messages/{mensaje_id}")
