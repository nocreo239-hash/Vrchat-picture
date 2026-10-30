"""Prueba de los avisos de instancias con VRChat y Discord falsos."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from avisos import instancias as av
from avisos.vrchat_api import totp

MUNDO = "wrld_b4d8a3fb-3e60-4305-8294-6a70cae985b6"
AHORA = dt.datetime(2026, 10, 30, 4, 0, tzinfo=dt.timezone.utc)


class VRFalso:
    def __init__(self):
        self.registro = []
        self.instancias = []

    def grupos_mios(self):
        return [{"name": "Otro grupo", "groupId": "grp_otro"}, {"name": "La Corte de los Cuervos", "groupId": "grp_cuervos"}]

    def registro_grupo(self, g):
        assert g == "grp_cuervos"
        return self.registro

    def mundo(self, m):
        return {"instances": self.instancias, "occupants": 7, "publicOccupants": 4, "privateOccupants": 3}


class DCFalso:
    def __init__(self):
        self.mensajes, self.creados = [], []

    def enviar(self, canal, texto, **k):
        self.mensajes.append((canal, texto))
        return {"id": "m"}


def entrada(i, quien, minutos, mundo=MUNDO):
    return {"id": f"gaud_{i}", "eventType": "group.instance.create", "actorDisplayName": quien,
            "created_at": (AHORA - dt.timedelta(minutes=minutos)).isoformat().replace("+00:00", "Z"),
            "targetId": f"{mundo}:12345~group(grp_cuervos)~groupAccessType(plus)~region(us)"}


def main():
    cfg = {"discord": {}, "avisos": {"mundo_id": MUNDO, "grupo_nombre": "cuervos"}}
    vr, dc, estado = VRFalso(), DCFalso(), {}
    av.canal_avisos = lambda dc, cfg, log=None: "canal-avisos"

    # 1) Primera pasada: lo que ya había no se avisa
    vr.registro = [entrada(1, "Viejo", 30)]
    vr.instancias = [["11111", 3]]
    m = av.pasada(cfg, vr, dc, estado, AHORA, log=lambda *a: None)
    assert m == [] and estado["iniciado"], m

    # 2) Alguien abre una de grupo y aparece una pública nueva
    vr.registro.append(entrada(2, "Lostkiller", 2))
    vr.registro.append(entrada(3, "Otro mundo", 1, mundo="wrld_otro"))
    vr.registro.append({"id": "gaud_4", "eventType": "group.member.join", "actorDisplayName": "X",
                        "created_at": AHORA.isoformat()})
    vr.instancias = [["11111", 3], ["22222", 1], ["33333~private(usr_x)", 2]]
    m = av.pasada(cfg, vr, dc, estado, AHORA, log=lambda *a: None)
    assert len(m) == 2, m
    assert "**Lostkiller** abrió una instancia Grupo+ · región US" in m[0], m[0]
    assert "pública" in m[1] and "1 persona" in m[1], m[1]
    assert "Ahora en Cuervos Club: **7**" in dc.mensajes[-1][1]

    # 3) Nada nuevo: no repite
    n = len(dc.mensajes)
    m = av.pasada(cfg, vr, dc, estado, AHORA, log=lambda *a: None)
    assert m == [] and len(dc.mensajes) == n

    # 4) El estado no guarda nombres ni IDs de instancia
    plano = str(estado)
    assert "Lostkiller" not in plano and "22222" not in plano and "gaud_" not in plano

    # 5) TOTP (vector de la RFC 6238 con la clave de prueba "12345678901234567890")
    import base64
    clave = base64.b32encode(b"12345678901234567890").decode()
    assert totp(clave, ahora=59, digitos=8) == "94287082"

    print("avisos: OK (5 escenarios)")


if __name__ == "__main__":
    main()
