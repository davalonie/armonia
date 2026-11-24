# Armonia

Armonia es un stack de musica autoalojado con una aplicacion web y una aplicacion Android compatible con Android Auto. Navidrome gestiona las cuentas y bibliotecas, Koito conserva las escuchas de cada usuario y Aurral proporciona las recomendaciones. El servidor de Armonia reune esas funciones en una sola interfaz.

![Biblioteca web con albumes ficticios del laboratorio](docs/screenshots/biblioteca.png)

## Que puedes hacer

- Explorar la biblioteca por artista, album o cancion, reproducir musica y ordenar la cola.
- Importar una playlist de Spotify desde su enlace o desde un CSV. Puedes revisar las coincidencias y elegir entre grabaciones cuando hay varias versiones.
- Buscar en YouTube y YouTube Music e incorporar grabaciones autorizadas a la biblioteca. Cada usuario trabaja con la carpeta de musica que tiene asignada en Navidrome.
- Escuchar en Android, gestionar las descargas y usar los controles de reproduccion desde Android Auto.

![Inicio de Armonia en el laboratorio](docs/screenshots/inicio.png)

## Instalar el stack de Armonia

Para una instalacion nueva en Linux con Docker Engine y Compose, ejecuta los pasos desde la raiz de este repositorio. El [Compose principal](docker-compose.yml) arranca el servidor con la web, Navidrome, Aurral y dos instancias privadas de Koito. Solo se publica Armonia, por defecto en `127.0.0.1:8000`.

**1. Prepara los directorios y las credenciales de esta instalacion.** Usa la cuenta de Linux que sera propietaria de los datos. Si su UID o GID difiere de 1000, ajusta `MUSIC_UID` y `MUSIC_GID` en `.env` a los valores de `id -u` e `id -g`. El preparador crea los secretos que falten y conserva los existentes.

```sh
cp -n .env.example .env
python3 scripts/prepare.py
```

**2. Elige si Aurral podra consultar artistas similares en Last.fm.** Para habilitarlo, registra una aplicacion en [Last.fm](https://www.last.fm/api/account/create), guarda su **API key** en `secrets/lastfm-api.key` y activa el [Compose de metadatos](compose.metadata.yaml). La clave se introduce sin mostrarla en la terminal. El trafico de metadatos de Aurral pasa por el servidor de Armonia.

```sh
python3 -c 'from getpass import getpass; from pathlib import Path; Path("secrets/lastfm-api.key").write_text(getpass("API key de Last.fm: ").strip()+"\n")'
```

Añade `COMPOSE_FILE=docker-compose.yml:compose.metadata.yaml` a `.env` para conservar esta seleccion en los siguientes arranques. Puedes omitir este paso si quieres empezar solo con biblioteca e historial. Para tres cuentas, añade tambien `COMPOSE_PROFILES=third-user` a `.env` antes del arranque.

**3. Construye y arranca los servicios.**

```sh
docker compose config --quiet
docker compose up --build -d --wait
```

**4. Crea y vincula las cuentas.** Desde el host Linux, usa Python 3.12 con `httpx`. Si ya preparaste el entorno de desarrollo, basta el ultimo comando. Cambia `alice bob` por uno o dos nombres de tu eleccion, o tres con el perfil anterior. Conserva el orden si repites el aprovisionamiento.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -c middleware/requirements.lock httpx
.venv/bin/python scripts/bootstrap.py --project armonia-stack --users alice bob
```

Las contraseñas generadas quedan en el archivo privado `secrets/bootstrap-users.json`. Entra en `http://localhost:8000` con tu cuenta. El primer inicio de sesion vincula la cuenta de Aurral asignada por el aprovisionamiento. Si usas otras credenciales o has desvinculado la cuenta, puedes conectarla desde **Ajustes → Recomendaciones**. Para el movil, configura un proxy HTTPS y fija `MUSIC_PUBLIC_ORIGIN` al origen correspondiente. Los datos persistentes quedan en `runtime/`; respalda tambien `secrets/` y tu configuracion local.

### Instalaciones anteriores y Navidrome externo

El [Compose minimo](compose.minimo.yaml) conserva la configuracion anterior. Si ya tienes datos con ese Compose, sigue usandolo en el mismo directorio y con el mismo nombre de proyecto. Para probar el stack completo en paralelo, usa otro clon y otro `MUSIC_PORT` para mantener separados los datos y los secretos. Si Docker indica `all predefined address pools have been fully subnetted`, asigna subredes libres a las redes del proyecto de prueba mediante un Compose local adicional.

- Con el Navidrome que incluia el perfil `full`: `docker compose -f compose.minimo.yaml --profile full up --build -d`. Navidrome escucha en `localhost:4533` y Armonia en `localhost:8000`.
- Con un Navidrome externo: configura `NAVIDROME_URL` y la carpeta compartida `MUSIC_DIR` en `.env` y ejecuta `docker compose -f compose.minimo.yaml up --build -d`.

Las asignaciones de biblioteca y los permisos de borrado se describen en la [guia de acceso](docs/ACCESO.md).

## Compilar e instalar Android

Prepara el entorno, proporciona la clave de firma mediante las variables documentadas y ejecuta el compilador desde la raiz. Al terminar, el script indica el directorio de salida. Instala la APK de release con `adb install -r RUTA_A_LA_APK`. Al abrir Armonia, introduce la URL HTTPS de tu servidor.

```sh
tools/preparar-entorno.sh
python3 tools/android/build_android.py
```

Las versiones del SDK, los pasos de firma y las pruebas del servidor, web y Android estan en la [guia del entorno](docs/ENTORNO.md).

## Dependencias de audio

El servidor usa **yt-dlp** para obtener enlaces de audio y descargar grabaciones de YouTube, y **FFmpeg** y **ffprobe** para procesar e inspeccionar archivos de audio. La imagen Docker incluye estas herramientas y Deno, que yt-dlp utiliza para resolver los desafios JavaScript de YouTube.

Si ejecutas el servidor o las pruebas fuera de Docker, instala el paquete de sistema `ffmpeg` (incluye `ffprobe` en Ubuntu) y las dependencias de Python con `python -m pip install -r middleware/requirements.lock` desde la raiz. La version de yt-dlp esta fijada en [requirements.lock](middleware/requirements.lock). Para reproducir desde YouTube fuera de Docker, instala tambien Deno y comprueba que este en el `PATH`.

### Album y artistas de una grabacion

La descarga conserva los creditos estructurados de la fuente. Con el Compose de metadatos, si una pista de YouTube Music solo indica su propio titulo como disco o carece de album, el servidor consulta el catalogo publico de Apple con el titulo y el artista. Utiliza una edicion de album solo si coinciden el titulo, los creditos completos y la duracion y hay un unico album candidato.

Para revisar un archivo existente, desde `middleware/` y con el entorno Python activo, ejecuta `python -m tools.review_recording_album "/ruta/cancion.m4a" > plan.json`. Comprueba los valores anteriores, la edicion propuesta y el enlace de evidencia. Si decides aplicarla, ejecuta `python -m tools.review_recording_album "/ruta/cancion.m4a" --aplicar plan.json --copia "/ruta/de/respaldo.m4a"` y reescanea la biblioteca de Navidrome. El segundo comando conserva el archivo original completo.

## SoundCloud

La API permite buscar pistas publicas con una aplicacion registrada y credenciales guardadas en el servidor. Para Armonia, la opcion de menor mantenimiento seria mostrar resultados con su autor y un enlace a la pista original. La reproduccion integrada exigiria respetar el acceso que el proveedor concede a cada pista, su atribucion y sus cuotas. [Guia de la API](https://developers.soundcloud.com/docs/api/guide) y [limites](https://developers.soundcloud.com/docs/api/rate-limits).

La copia a Navidrome, las descargas al telefono y la cache persistente de Android son incompatibles con las condiciones generales de la API para el contenido obtenido por esa via. Usar yt-dlp para obtener el audio no resuelve esa limitacion. Armonia mantiene esta fuente fuera de las importaciones. [Condiciones de SoundCloud, Caching and Downloading](https://developers.soundcloud.com/docs/api/terms-of-use#caching-and-downloading).

## Descargas de YouTube

Descarga unicamente contenido cuya descarga este autorizada por el servicio y para el que tengas los derechos o permisos correspondientes. Consulta las [condiciones de uso de YouTube](https://www.youtube.com/static?template=terms).

## Creditos

Armonia es una obra derivada de Kobser, de Stefan Muri y colaboradores, distribuida bajo GPL-3.0. Las modificaciones de Armonia comenzaron en noviembre de 2026. [Proyecto original](https://github.com/stefan-muri/kobser).

La importacion desde CSV admite las listas de Spotify exportadas con Exportify, de watsonbox. [Exportify](https://github.com/watsonbox/exportify).

## Licencia

Armonia se distribuye bajo GPL-3.0. [Texto de la licencia](LICENSE).

## Authentik y APK Capacitor

Puedes añadir el acceso con Authentik y probar **Armonia Capacitor** junto al cliente Kotlin. La guía incluye el grupo y los retornos OIDC, la vinculación de cuentas existentes, los comandos de compilación y la prueba de reproducción sin conexión. [Configurar Authentik y probar las dos APK](docs/AUTHENTIK_Y_ANDROID.md)
