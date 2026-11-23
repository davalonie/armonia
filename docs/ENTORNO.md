# Entorno de desarrollo de Armonia

## Inventario del laboratorio

Versiones comprobadas el 22 de noviembre de 2026.

| Componente | Version instalada | Comprobacion |
| --- | --- | --- |
| Android SDK Platform | Android 17, API 37.0, extension 22, revision 2 | Metadatos del SDK. Las carpetas locales `android-37.0` y `android-37.0-2` contienen la misma revision declarada. |
| Android SDK Build-Tools | 36.0.0 | Metadatos del paquete |
| Android SDK Platform-Tools | 37.0.1 | Metadatos del paquete |
| Android Emulator | 37.3.8 | Metadatos del emulador |
| Imagen del emulador | API 35, `default;x86_64`, revision 2 | Metadatos de la imagen |
| Gradle | 9.7.1 | Distribucion fijada en las propiedades del wrapper |
| Python | 3.12.3 | Interprete del entorno virtual |
| Node.js y npm | 24.20.0 y 11.19.0 | Ejecutables del host |
| Playwright para Python | 1.65.0 | Paquete instalado en el entorno virtual |
| Chromium Headless Shell | 158.0.8127.18, compilacion 1254 | Ejecutable en la cache del laboratorio |
| WebKit | 27.2, compilacion 2388 | Manifiesto de Playwright y carpeta de instalacion con MiniBrowser |
| FFmpeg de Playwright | Compilacion 1013 | Cache del laboratorio |

El SDK inventariado carece del directorio `cmdline-tools`. Los navegadores de escritorio del host son Google Chrome 157.0.8103.50 y Firefox 158.0.1. La cache de Playwright del usuario tambien contiene Chromium 151.0.7922.34 (compilacion 1234), Chromium Headless Shell 1234 y FFmpeg 1011. Las pruebas del proyecto disponen de las versiones de la tabla.

## Preparar una estacion Linux x86-64

Instala Python 3.12 con `venv`, Node 24 con npm, JDK 25, Docker con Compose, Bubblewrap (`bwrap`), FFmpeg, curl y unzip. Exporta `JAVA_HOME` apuntando al JDK. Para los paquetes del sistema que requiera el navegador, Playwright ofrece `python -m playwright install-deps chromium webkit`. [Python](https://docs.python.org/3.12/library/venv.html) · [Node.js](https://nodejs.org/en/download) · [Docker Compose](https://docs.docker.com/compose/) · [Playwright](https://playwright.dev/python/docs/browsers).

Ejecuta `tools/preparar-entorno.sh` desde el clon. Descarga las herramientas de Android, instala las dependencias de Python y la web, compila la web y genera 44 pistas ficticias. El SDK puede solicitar que aceptes sus licencias. El script verifica las revisiones instaladas. Las siete conversiones del laboratorio historico eran productos de la cache de reproduccion. [Android command-line tools](https://developer.android.com/studio#command-line-tools-only) · [Gradle Wrapper](https://docs.gradle.org/current/userguide/gradle_wrapper.html).

El instalador descarga `gradle-9.7.1-bin.zip` desde la URL de `android/gradle/wrapper/gradle-wrapper.properties` y contrasta el archivo con `distributionSha256Sum` de ese mismo fichero. Si la suma falla, descarta la descarga y termina con error. El ZIP verificado queda en `wrapper/dists/` dentro de `GRADLE_USER_HOME`. En su primer arranque, el wrapper puede descomprimirlo desde esa cache dentro de Bubblewrap. Si personalizas `GRADLE_USER_HOME`, exporta la misma ruta absoluta antes de preparar el entorno y antes de compilar. [Distribuciones oficiales de Gradle](https://gradle.org/releases/)

| Variable | Uso | Valor por defecto |
| --- | --- | --- |
| `PYTHON` | Interprete para crear el venv | `python3.12` |
| `ARMONIA_VENV` | Ruta absoluta del entorno de Python | `.venv` en el clon |
| `JAVA_HOME` | JDK de la compilacion Android | Requerida |
| `ANDROID_HOME` | SDK local | `runtime/android-sdk` |
| `GRADLE_USER_HOME` | Cache de Gradle | `runtime/android/gradle-cache` |
| `PLAYWRIGHT_BROWSERS_PATH` | Cache de los navegadores | El instalador usa `runtime/browsers` |
| `ARMONIA_CHROMIUM` | Ejecutable Chromium alternativo para el driver web | El de Playwright |
| `DOCKER_CONFIG` | Directorio de configuracion Docker del laboratorio y las herramientas de release | `runtime/docker-config` |

## Pruebas

Activa el venv en cada terminal. En los ejemplos siguientes, ejecuta los comandos desde la raiz del clon.

```sh
. .venv/bin/activate
(cd middleware && ruff check . && pytest -q tests)
(cd middleware/frontend && npm test && npm run build)
export PLAYWRIGHT_BROWSERS_PATH="$PWD/runtime/browsers"
python tools/lab/lab.py up
python tools/lab/lab.py seed
python tools/lab/lab.py server
```

El servidor de pruebas se queda en primer plano en `127.0.0.1:18480`. En otra terminal ejecuta `python tools/web/web.py tools/web/recorrido.py` con el mismo venv y la misma cache de navegadores. El recorrido inicia sesion, visita Inicio y Biblioteca y guarda las capturas en `runtime/capturas/`. Al terminar, interrumpe el servidor con Ctrl+C y ejecuta `python tools/lab/lab.py down`. Los datos del laboratorio se conservan en `runtime/lab/`.

## Firma de Android

Guarda el almacen de claves y su archivo de contraseña en `firma-android/` (git solo sigue su README; ver [`firma-android/README.md`](../firma-android/README.md)), con acceso exclusivo de tu usuario (`chmod 700 firma-android`, `chmod 600` en los archivos). Reserva `secrets/` para las credenciales del servidor. Ten una copia cifrada fuera del equipo: sin ella no podras instalar actualizaciones sobre la app ya instalada. No uses `git clean -x` en el clon, porque borra los archivos ignorados. Exporta `MUSIC_KEYSTORE_FILE` y `MUSIC_KEYSTORE_PASSWORD_FILE` con sus rutas absolutas y `MUSIC_KEY_ALIAS` con el alias de la entrada. Si la entrada tiene una contraseña distinta, el compilador admite `MUSIC_KEY_PASSWORD` en el entorno del proceso. Para invocar Gradle directamente, proporciona `MUSIC_KEYSTORE_PASSWORD` mediante tu gestor de secretos.

```sh
python3 tools/android/build_android.py :app:assembleRelease :app:testDebugUnitTest --max-workers=1
```

El compilador aisla el proyecto con Bubblewrap, monta la clave en modo de lectura y utiliza el wrapper de Gradle 9.7.1. Las APK y los informes XML quedan en subdirectorios de `runtime/android/`.

En la maquina del inventario (7 GiB de RAM), la validacion de release y las pruebas JVM se ejecutan en serie con dependencias ya almacenadas. Este comando excluye el analisis de Android Lint de release y limita el proceso de compilacion Kotlin a la misma JVM.

```sh
python3 tools/android/build_android.py :app:assembleRelease :app:testDebugUnitTest \
  --offline --max-workers=1 -x :app:lintVitalAnalyzeRelease \
  -Pkotlin.compiler.execution.strategy=in-process \
  '-Dorg.gradle.jvmargs=-Xmx1280m -XX:MaxMetaspaceSize=512m -XX:ActiveProcessorCount=2 -Dfile.encoding=UTF-8'
```

## Probar una imagen y actualizar el servicio

Con la imagen ya construida, ejecuta `python tools/release/smoke.py armonia:0.7.0`. La prueba utiliza el arranque normal de la imagen en un contenedor efimero, sin red, y comprueba salud, web, SQLite y FFmpeg.

Para una instalacion posterior, `tools/release/deploy.py --help` describe los parametros de la plantilla. Proporciona el directorio del stack, todos los archivos Compose activos en orden, la etiqueta de destino, el ID de la imagen en uso y el commit esperado. La imagen nueva debe llevar la etiqueta OCI `org.opencontainers.image.revision` con ese commit. El stack debe seleccionar la imagen mediante `MUSIC_IMAGE`. El despliegue comprueba las operaciones pendientes, detiene unicamente `music` y guarda una copia cifrada de sus datos y configuracion en `backups/` antes del cambio. Conserva la clave externa para poder recuperar esa copia. Si la validacion falla, el script intenta arrancar la imagen previa.
