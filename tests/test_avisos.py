"""Prueba de los avisos de instancias con VRChat y Discord falsos."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from avisos import instancias as av
from avisos.vrchat_api import totp, VRChatError

MUNDO = "wrld_b4d8a3fb-3e60-4305-8294-6a70cae985b6"
AHORA = dt.datetime(2026, 10, 30, 4, 0, tzinfo=dt.timezone.utc)


class VRFalso:
    def __init__(self):
        self.registro = []
        self.instancias = []
        self.publicaciones = []
        self.falla_publicar = False

    def publicar_grupo(self, g, titulo, texto, notificar=True, visibilidad="group"):
        if self.falla_publicar:
            raise VRChatError("VRChat 403 en POST /groups/x/posts: sin permiso")
        assert g == "grp_cuervos" and notificar and visibilidad == "group"
        self.publicaciones.append((titulo, texto))
        return {"id": "gpost_x"}

    def grupos_mios(self):
        return [{"name": "Otro grupo", "groupId": "grp_otro"}, {"name": "La Corte de los Cuervos", "groupId": "grp_cuervos"}]

    def registro_grupo(self, g):
        assert g == "grp_cuervos"
        return self.registro

    def grupo(self, g):
        return {"name": "Hipnotic"}

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
    cfg = {"discord": {}, "avisos": {"mundo_id": MUNDO, "grupo_nombre": "cuervos", "publicar_en_grupo": True,
                                     "horas_entre_publicaciones": 2,
                                     "publicacion_texto": "{quien} abrió una instancia {tipo}. ¡Pasa!"}}
    vr, dc, estado = VRFalso(), DCFalso(), {}
    av.canal_avisos = lambda dc, cfg, log=None: "canal-avisos"

    # 1) Primera pasada: lo que ya había no se avisa
    vr.registro = [entrada(1, "Viejo", 30)]
    vr.instancias = [["11111", 3]]
    m = av.pasada(cfg, vr, dc, estado, AHORA, log=lambda *a: None)
    assert m == [] and estado["iniciado"], m
    assert vr.publicaciones == [], "la primera pasada no publica"

    # 2) Alguien abre una de grupo y aparece una pública nueva
    vr.registro.append(entrada(2, "Lostkiller", 2))
    vr.registro.append(entrada(3, "Otro mundo", 1, mundo="wrld_otro"))
    vr.registro.append({"id": "gaud_4", "eventType": "group.member.join", "actorDisplayName": "X",
                        "created_at": AHORA.isoformat()})
    vr.instancias = [["11111", 3], ["22222~region(us)", 1], ["33333~private(usr_x)", 2],
                     ["44444~group(grp_cuervos)~groupAccessType(public)", 5],
                     ["55555~group(grp_otro)~groupAccessType(public)~region(eu)", 4]]
    m = av.pasada(cfg, vr, dc, estado, AHORA, log=lambda *a: None)
    assert len(m) == 3, m
    assert "**Hipnotic**" in m[2] and "región EU" in m[2] and "4 personas" in m[2], m[2]
    assert "**Lostkiller** abrió una instancia Grupo+ · región US" in m[0], m[0]
    assert "pública" in m[1] and "1 persona" in m[1], m[1]
    assert "Ahora en Cuervos Club: **7**" in dc.mensajes[-1][1]
    # una sola publicación en el grupo, por la instancia de grupo (no por las públicas)
    assert vr.publicaciones == [("La casa está abierta", "Lostkiller abrió una instancia Grupo+ · región US. ¡Pasa!")], vr.publicaciones

    # 3) Nada nuevo: no repite
    n = len(dc.mensajes)
    m = av.pasada(cfg, vr, dc, estado, AHORA, log=lambda *a: None)
    assert m == [] and len(dc.mensajes) == n

    # 3b) Otra instancia de grupo a la hora: avisa en Discord pero no vuelve a notificar en VRChat
    vr.registro.append(entrada(5, "Ana", 1))
    m = av.pasada(cfg, vr, dc, estado, AHORA + dt.timedelta(hours=1), log=lambda *a: None)
    assert len(m) == 1 and len(vr.publicaciones) == 1, (m, vr.publicaciones)

    # 3c) Solo una pública nueva, pasadas 3 h: no publica en el grupo
    vr.instancias.append(["66666~region(jp)", 2])
    m = av.pasada(cfg, vr, dc, estado, AHORA + dt.timedelta(hours=3), log=lambda *a: None)
    assert len(m) == 1 and len(vr.publicaciones) == 1, (m, vr.publicaciones)

    # 3d) Sin permiso para publicar: el aviso de Discord sale igual y no rompe
    t = AHORA + dt.timedelta(hours=4)
    vr.registro.append({**entrada(6, "Beto", 0), "created_at": t.isoformat().replace("+00:00", "Z")})
    vr.falla_publicar = True
    avisos_log = []
    m = av.pasada(cfg, vr, dc, estado, t, log=avisos_log.append)
    assert len(m) == 1 and any("No pude publicar" in x for x in avisos_log), avisos_log
    # y cuando vuelve a tener permiso, publica
    vr.falla_publicar = False
    t2 = t + dt.timedelta(minutes=20)
    vr.registro.append({**entrada(7, "Caro", 0), "created_at": t2.isoformat().replace("+00:00", "Z")})
    av.pasada(cfg, vr, dc, estado, t2, log=lambda *a: None)
    assert len(vr.publicaciones) == 2 and vr.publicaciones[-1][1].startswith("Caro"), vr.publicaciones

    # 3e) Apagado en la config: no publica
    cfg["avisos"]["publicar_en_grupo"] = False
    t3 = t2 + dt.timedelta(hours=5)
    vr.registro.append({**entrada(8, "Dani", 0), "created_at": t3.isoformat().replace("+00:00", "Z")})
    av.pasada(cfg, vr, dc, estado, t3, log=lambda *a: None)
    assert len(vr.publicaciones) == 2

    # 4) El estado no guarda nombres ni IDs de instancia
    plano = str(estado)
    assert "Lostkiller" not in plano and "Caro" not in plano and "22222" not in plano and "gaud_" not in plano

    # 5) TOTP (vector de la RFC 6238 con la clave de prueba "12345678901234567890")
    import base64
    clave = base64.b32encode(b"12345678901234567890").decode()
    assert totp(clave, ahora=59, digitos=8) == "94287082"

    print("avisos: OK (10 escenarios)")


if __name__ == "__main__":
    main()
