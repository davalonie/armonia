# Armonía

Armonía es un reproductor de música autoalojado. El servidor conecta la biblioteca de Navidrome con una aplicación web y una aplicación Android compatible con Android Auto. Inicias sesión con tu cuenta de Navidrome y accedes a tus álbumes, canciones, favoritas y listas.

![Biblioteca web con álbumes ficticios del laboratorio](docs/screenshots/biblioteca.png)

## Qué puedes hacer

- Explorar la biblioteca por artista, álbum o canción, reproducir música y ordenar la cola.
- Importar una playlist de Spotify desde su enlace o desde un CSV. Puedes revisar las coincidencias y elegir entre grabaciones cuando hay varias versiones.
- Buscar en YouTube y YouTube Music e incorporar grabaciones autorizadas a la biblioteca. Cada usuario trabaja con la carpeta de música que tiene asignada en Navidrome.
- Escuchar en Android, gestionar las descargas y usar los controles de reproducción desde Android Auto.

![Inicio de Armonía en el laboratorio](docs/screenshots/inicio.png)

## Instalar el servidor y la web

Desde la raíz del repositorio, prepara los directorios y la configuración local. La imagen de Armonía se ejecuta con UID y GID 1000. Ese usuario debe poder escribir en los directorios de música y datos de la aplicación.

```sh
mkdir -p runtime/music runtime/armonia runtime/navidrome secrets
cp -n .env.example .env
docker compose --profile full up --build -d
```

Abre `http://localhost:4533` para crear la cuenta inicial de Navidrome. Después entra en `http://localhost:8000` con esa cuenta. Por defecto, los puertos escuchan en la interfaz local del servidor. Para acceder desde el móvil, expón la web mediante el acceso HTTPS privado de tu instalación.

Si ya tienes Navidrome, configura `NAVIDROME_URL` con una dirección accesible desde el contenedor y `MUSIC_DIR` con la biblioteca compartida. Ejecuta `docker compose up --build -d`. Los ajustes de puertos y rutas están en [.env.example](.env.example).

Las asignaciones de biblioteca y los permisos de borrado se describen en la [guía de acceso](docs/ACCESO.md).

## Compilar e instalar Android

Prepara el entorno, proporciona la clave de firma mediante las variables documentadas y ejecuta el compilador desde la raíz. Al terminar, el script indica el directorio de salida. Instala la APK de release con `adb install -r RUTA_A_LA_APK`. Al abrir Armonía, introduce la URL HTTPS de tu servidor.

```sh
tools/preparar-entorno.sh
python3 tools/android/build_android.py
```

Las versiones del SDK, los pasos de firma y las pruebas del servidor, web y Android están en la [guía del entorno](docs/ENTORNO.md).

## Descargas de YouTube

Descarga únicamente contenido cuya descarga esté autorizada por el servicio y para el que tengas los derechos o permisos correspondientes. Consulta las [condiciones de uso de YouTube](https://www.youtube.com/static?template=terms).

## Créditos

Armonía es una obra derivada de Kobser, de Stefan Muri y colaboradores, distribuida bajo GPL-3.0. Las modificaciones de Armonía comenzaron en noviembre de 2026. [Proyecto original](https://github.com/stefan-muri/kobser).

La importación desde CSV admite las listas de Spotify exportadas con Exportify, de watsonbox. [Exportify](https://github.com/watsonbox/exportify).

## Licencia

Armonía se distribuye bajo GPL-3.0. [Texto de la licencia](LICENSE).
