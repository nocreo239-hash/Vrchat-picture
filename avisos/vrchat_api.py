"""Cliente mínimo de la API de VRChat (la no oficial que usan VRCX y compañía), solo lectura.

Inicia sesión con usuario + contraseña + código 2FA de app autenticadora (TOTP), y guarda la
sesión cifrada para no volver a iniciarla en cada pasada (VRChat mira mal los logins seguidos).
"""

import base64
import hashlib
import hmac
import json
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie

API = "https://api.vrchat.cloud/api/1"
AGENTE = "CuervosClubAvisos/1.0 (bot de avisos de instancias; contacto: allan_martian en VRChat)"


class VRChatError(Exception):
    pass


def totp(secreto_base32, ahora=None, digitos=6, periodo=30):
    """Código de 6 cifras como el de la app autenticadora (RFC 6238)."""
    s = secreto_base32.replace(" ", "").upper()
    s += "=" * (-len(s) % 8)
    clave = base64.b32decode(s)
    contador = int((ahora or time.time()) // periodo)
    h = hmac.new(clave, struct.pack(">Q", contador), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    n = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digitos)
    return str(n).zfill(digitos)


class VRChat:
    def __init__(self, usuario, contrasena, secreto_totp, cookies=None, pausa=1.0):
        if not (usuario and contrasena):
            raise VRChatError("Faltan los secretos VRC_USUARIO y VRC_CONTRASENA.")
        self.usuario, self.contrasena, self.secreto = usuario, contrasena, secreto_totp
        self.cookies = dict(cookies or {})
        self.pausa = pausa      # entre llamadas: la API limita a pocas por segundo
        self.yo = None

    # ------------------------------------------------------------ base
    def _pedir(self, metodo, ruta, cuerpo=None, auth_basica=False):
        url = API + ruta
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(url, data=datos, method=metodo)
        req.add_header("User-Agent", AGENTE)
        if datos is not None:
            req.add_header("Content-Type", "application/json")
        if self.cookies:
            req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()))
        if auth_basica:
            par = f"{urllib.parse.quote(self.usuario)}:{urllib.parse.quote(self.contrasena)}"
            req.add_header("Authorization", "Basic " + base64.b64encode(par.encode()).decode())
        time.sleep(self.pausa)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                self._guardar_cookies(r.headers.get_all("Set-Cookie") or [])
                t = r.read()
                return json.loads(t) if t else None
        except urllib.error.HTTPError as e:
            self._guardar_cookies(e.headers.get_all("Set-Cookie") or [])
            texto = e.read().decode("utf-8", "replace")[:300]
            if e.code == 401:
                raise VRChatError(f"401: {texto}")
            if e.code == 429:
                raise VRChatError("VRChat pidió ir más despacio (429). Se reintenta en la próxima pasada.")
            raise VRChatError(f"VRChat {e.code} en {metodo} {ruta}: {texto}")

    def _guardar_cookies(self, cabeceras):
        for c in cabeceras:
            sc = SimpleCookie()
            sc.load(c)
            for k, m in sc.items():
                if k in ("auth", "twoFactorAuth"):
                    self.cookies[k] = m.value

    # ------------------------------------------------------------ sesión
    def sesion_valida(self, log=print):
        if "auth" not in self.cookies:
            log(f"Sesión guardada: sin cookie auth (tengo: {', '.join(self.cookies) or 'nada'})")
            return False
        try:
            r = self._pedir("GET", "/auth")
            if not (r and r.get("ok")):
                log(f"Sesión guardada rechazada: {str(r)[:120]}")
            return bool(r and r.get("ok"))
        except VRChatError as e:
            log(f"Sesión guardada no válida: {str(e)[:160]}")
            return False

    def entrar(self):
        """Usa la sesión guardada si sigue viva; si no, inicia sesión con 2FA."""
        if self.sesion_valida():
            self.yo = self._pedir("GET", "/auth/user")
            if self.yo and self.yo.get("id"):
                return False   # no hizo falta iniciar sesión
        self.cookies = {}
        r = self._pedir("GET", "/auth/user", auth_basica=True) or {}
        metodos = r.get("requiresTwoFactorAuth") or []
        if metodos:
            if "totp" not in metodos:
                raise VRChatError("La cuenta del bot pide el código por correo. Actívale la verificación en dos "
                                  "pasos con app autenticadora y guarda su clave en el secreto VRC_TOTP.")
            if not self.secreto:
                raise VRChatError("La cuenta tiene 2FA: falta el secreto VRC_TOTP (la clave de la app autenticadora).")
            v = self._pedir("POST", "/auth/twofactorauth/totp/verify", {"code": totp(self.secreto)}) or {}
            if not v.get("verified"):
                raise VRChatError("VRChat no aceptó el código 2FA. Revisa el secreto VRC_TOTP.")
            r = self._pedir("GET", "/auth/user") or {}
        if not r.get("id"):
            raise VRChatError("No pude iniciar sesión en VRChat con la cuenta del bot.")
        self.yo = r
        return True

    # ------------------------------------------------------------ lectura
    def grupos_mios(self):
        return self._pedir("GET", f"/users/{self.yo['id']}/groups") or []

    def registro_grupo(self, grupo_id, n=50):
        q = urllib.parse.urlencode({"n": n})
        return (self._pedir("GET", f"/groups/{grupo_id}/auditLogs?{q}") or {}).get("results", [])

    def instancias_grupo(self, grupo_id):
        return self._pedir("GET", f"/groups/{grupo_id}/instances") or []

    def mundo(self, mundo_id):
        return self._pedir("GET", f"/worlds/{mundo_id}") or {}
