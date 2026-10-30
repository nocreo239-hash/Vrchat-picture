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
        self.vistas = []        # diagnóstico: qué cookies mandó VRChat (solo nombre y largo)

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
        # A mano: SimpleCookie descarta en silencio cookies con atributos nuevos (p. ej. "Partitioned")
        for c in cabeceras:
            par = c.split(";", 1)[0].strip()
            if "=" not in par:
                continue
            k, v = par.split("=", 1)
            k, v = k.strip(), v.strip().strip('"')
            if k in ("auth", "twoFactorAuth"):
                self.vistas.append(f"{k}({len(v)}{'=' if self.cookies.get(k) == v else '*'})")
                if v:
                    self.cookies[k] = v
                else:
                    self.cookies.pop(k, None)   # VRChat la borró

    # ------------------------------------------------------------ sesión
    def _resumen_cookies(self):
        return ", ".join(f"{k}({len(v)})" for k, v in self.cookies.items()) or "ninguna"

    def entrar(self, log=print):
        """Usa la sesión guardada si sigue viva; si no, inicia sesión con 2FA.
        Devuelve True si tuvo que iniciar sesión con contraseña."""
        if "auth" in self.cookies:
            log(f"::notice::Sesión guardada: cookies {self._resumen_cookies()}")
            try:
                r = self._pedir("GET", "/auth/user") or {}
                if r.get("id"):
                    self.yo = r
                    return False
                if "totp" in (r.get("requiresTwoFactorAuth") or []) and self.secreto:
                    # la sesión sigue, solo pide otra vez el 2FA: no hace falta la contraseña
                    if self._verificar_2fa():
                        r = self._pedir("GET", "/auth/user") or {}
                        if r.get("id"):
                            self.yo = r
                            log("::notice::Sesión guardada reutilizada (solo pidió el 2FA).")
                            return False
                log(f"::notice::Sesión guardada rechazada: {str(r)[:120]}")
            except VRChatError as e:
                log(f"::notice::Sesión guardada no válida: {str(e)[:160]}")
        self.cookies = {}
        r = self._pedir("GET", "/auth/user", auth_basica=True) or {}
        metodos = r.get("requiresTwoFactorAuth") or []
        if metodos:
            if "totp" not in metodos:
                raise VRChatError("La cuenta del bot pide el código por correo. Actívale la verificación en dos "
                                  "pasos con app autenticadora y guarda su clave en el secreto VRC_TOTP.")
            if not self.secreto:
                raise VRChatError("La cuenta tiene 2FA: falta el secreto VRC_TOTP (la clave de la app autenticadora).")
            if not self._verificar_2fa():
                raise VRChatError("VRChat no aceptó el código 2FA. Revisa el secreto VRC_TOTP.")
            r = self._pedir("GET", "/auth/user") or {}
        if not r.get("id"):
            raise VRChatError("No pude iniciar sesión en VRChat con la cuenta del bot.")
        self.yo = r
        log(f"::notice::Sesión nueva: cookies {self._resumen_cookies()}")
        return True

    def _verificar_2fa(self):
        v = self._pedir("POST", "/auth/twofactorauth/totp/verify", {"code": totp(self.secreto)}) or {}
        return bool(v.get("verified"))

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
