# Tendedero de Polaroids para VRChat

Tu comunidad manda fotos a un canal de Discord, los admins las aprueban con una reacción, y aparecen
como Polaroids colgadas en tu mundo de VRChat, con el nombre de quien la mandó escrito en el marco.

- **5 pinzas VIP** (no caducan) y **15 comunitarias** (duran 7 días y rotan cada 6 horas si hay más).
- Todo gratis: usa tu propio bot de Discord y tu propia cuenta de GitHub. No hay servidores que pagar.
- Funciona en PC y Quest: el mundo descarga **una sola imagen** con todas las fotos (5 segundos).

**Tiempo de instalación: unos 20 minutos.** No hace falta saber programar.

---

## Cómo funciona

1. Alguien pega su foto en el canal público (por ejemplo `#manda-tu-polaroid`).
2. El bot la pasa al canal privado de revisión y borra la del canal público.
3. Un admin reacciona: ✅ aprobar · ⭐ aprobar como VIP · ❌ rechazar.
4. En 10–20 minutos la foto aparece en el mundo.
5. Para quitar una foto ya publicada, el admin reacciona ❌ en su mensaje de revisión.

---

## Paso 1 — Crear el bot de Discord (5 min)

1. Entra a <https://discord.com/developers/applications> y pulsa **New Application**. Ponle un nombre (ej. "Tendedero").
2. En el menú de la izquierda, entra a **Bot**:
   - Pulsa **Reset Token** y copia el token. **Guárdalo, no lo compartas con nadie.**
   - Más abajo, activa **Message Content Intent** y guarda.
3. Entra a **OAuth2 → URL Generator**:
   - En *Scopes* marca **bot**.
   - En *Bot Permissions* marca: **View Channels, Send Messages, Attach Files, Add Reactions,
     Read Message History, Manage Messages, Manage Channels, View Audit Log**.
   - Copia la URL de abajo, ábrela y añade el bot a tu servidor.

## Paso 2 — Los canales (0 min)

No tienes que hacer nada: en la primera pasada el bot crea `#manda-tu-polaroid` (público) y
`#revision-polaroids` (privado, solo para administradores). Quien pueda ver el canal de revisión puede
aprobar fotos; si quieres que otros revisen, dales *Ver canal* ahí.

¿Prefieres crearlos tú o usar otros nombres? Créalos y pon sus nombres en `config.yml`.

## Paso 3 — Crear tu repositorio en GitHub (5 min)

1. Entra a la página de esta plantilla y pulsa **Use this template → Create a new repository**.
   - Déjalo **Public** (GitHub Pages gratis solo funciona con repositorios públicos; las fotos
     aprobadas son públicas de todas formas, porque el mundo las descarga).
2. En tu repositorio nuevo, entra a **Settings → Pages** y en *Source* elige **GitHub Actions**.
3. Entra a **Settings → Secrets and variables → Actions → New repository secret**:
   - Nombre: `DISCORD_TOKEN`
   - Valor: el token del bot del paso 1.

## Paso 4 — Configurar (1 min, opcional)

Si usaste los nombres de canal de arriba, no tienes que tocar nada. En `config.yml` puedes cambiar los
textos, los colores, cuántas pinzas hay y cada cuánto rotan. Pulsa el lápiz para editar y **Commit changes**.

Al guardar, el tendedero se ejecuta solo. Para comprobarlo, entra a la pestaña **Actions**: debe aparecer
"Tendedero" en verde. Después abre:

```
https://TU_USUARIO.github.io/TU_REPOSITORIO/
```

Ahí ves cómo se ve el tendedero ahora mismo.

## Paso 5 — Poner el tendedero en tu mundo (Unity, 5 min)

1. Importa el paquete del tendedero en tu proyecto de VRChat (SDK de mundos 3.4 o más nuevo).
2. Abre **Tendedero Polaroid → Configurar**.
3. Pega la dirección de tu página (`https://TU_USUARIO.github.io/TU_REPOSITORIO/`) y pulsa **Probar conexión**.
4. Pulsa **Crear tendedero en la escena**, muévelo a su sitio (la flecha azul mira hacia la gente) y sube el mundo.

---

## Mudar el tendedero a otro servidor

1. Invita el bot al servidor nuevo. El enlace aparece en cada pasada, en **Actions → Tendedero → (la última) →
   notas**, y ya trae el permiso de *Gestionar canales*.
2. Listo. En la siguiente pasada (10–20 min) el bot crea `#manda-tu-polaroid` y el canal de revisión
   (privado: solo lo ven el bot y los roles de administrador) y empieza a trabajar ahí.
   Las fotos ya colgadas se quedan.

**Invitarlo desde el propio Discord** (botón *Agregar app* en el perfil del bot): en el portal de
desarrolladores activa **Bot → Public Bot**, y en **Installation** elige *Install Link: Discord Provided
Link*, con el scope `bot` y los permisos del paso 1. Es seguro gracias al **candado**: el bot solo trabaja
en servidores cuyo dueño seas tú **o a los que tú lo añadiste** (por ejemplo, uno donde eres admin; para
saberlo mira el registro de auditoría, por eso pide *View Audit Log*). Si alguien lo añade a su servidor, lo ignora (o se sale, con
`salir_de_ajenos: true`). Para permitir el servidor de un amigo, pon su ID de usuario en `duenos_permitidos`.

El bot trabaja en **el último servidor tuyo al que lo invitaste**. Para fijar uno, pon su ID en `servidor`
en `config.yml`. Si no quieres que cree canales solo, pon `crear_canales: false`.

## Ajustes útiles (`config.yml`)

| Ajuste | Qué hace |
|---|---|
| `vip` / `comunitarias` | Cuántas pinzas de cada tipo. Tienen que sumar `columnas × filas` (20 por defecto). |
| `horas_rotacion` | Cada cuánto rotan las comunitarias si hay más que pinzas. |
| `dias_caducidad` | Cuántos días dura una foto comunitaria. |
| `vacias` | `invitacion` muestra "¡Tu foto aquí!" en las pinzas libres; `ocultar` las esconde. |
| `borrar_original` | Borra la foto del canal público al pasarla a revisión. |

## Preguntas frecuentes

**¿Por qué tarda 10–20 minutos?** GitHub ejecuta el tendedero cada 10 minutos (a veces se retrasa un poco),
y GitHub Pages tarda unos minutos más en publicar.

**¿Por qué GitHub y no otro hosting?** VRChat solo descarga imágenes de una lista de sitios confiables,
y `github.io` está en ella. Con otros sitios, la mayoría de los jugadores no vería las fotos.

**¿Cuánto cuesta?** Nada: Discord, GitHub Actions (en repositorios públicos) y GitHub Pages son gratis.

**El bot no hace nada.** Revisa en **Actions** el último "Tendedero": el mensaje en rojo dice qué falta.
Lo más común: el token mal copiado, no activar *Message Content Intent*, o que el bot no tenga permiso en algún canal.

**GitHub apagó la tarea.** GitHub pausa las tareas programadas de repositorios sin actividad en 60 días. El
tendedero hace un pequeño guardado diario para evitarlo. Si aun así se pausa, entra a **Actions** y vuelve a activarla.

---

Fuente de los nombres: [Caveat](https://fonts.google.com/specimen/Caveat), licencia SIL Open Font License
(incluida en `fuentes/Caveat-OFL.txt`).

## Avisos de instancias (opcional)

El bot puede escribir en un canal privado de Discord (`#avisos-instancias`, lo crea solo) cada vez que
se abre una instancia de tu mundo:

- **De grupo:** dice quién la abrió y de qué tipo es (Grupo+, solo miembros…).
- **Pública:** avisa que hay una nueva y cuánta gente tiene (VRChat no dice quién la abrió).
- Las Friends / Invite de otras personas no se pueden ver: son privadas.

Usa una **cuenta secundaria de VRChat** (nunca la principal):

1. Entra con esa cuenta en vrchat.com → Settings → **Two-Factor Authentication** → activa la app
   autenticadora. Cuando salga el código QR, pulsa la opción para escribir la clave a mano y **copia esa
   clave** (letras y números). Termina de activarla con tu app autenticadora como siempre.
2. Mete esa cuenta en tu grupo y dale un rol con permiso de **ver el registro** (audit log).
3. En GitHub: **Settings → Secrets and variables → Actions → New repository secret**, crea tres:
   - `VRC_USUARIO`: el usuario o correo de la cuenta secundaria
   - `VRC_CONTRASENA`: su contraseña
   - `VRC_TOTP`: la clave del paso 1

La sesión de VRChat se guarda cifrada en `data/vrc_sesion.enc` para no iniciar sesión en cada pasada.
En el repositorio solo quedan huellas, nunca nombres ni IDs de instancia. Se apaga con
`avisos: activado: false` en `config.yml`.

Los avisos salen en cada pasada del bot: si GitHub tarda en lanzar las pasadas programadas, llegan tarde.
