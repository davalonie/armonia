# firma-android

Esta carpeta guarda **tu** clave de firma de la app Android. Git solo sigue este README: los archivos de clave están
excluidos en `.gitignore` y nunca se suben.

## Qué va aquí

| Archivo | Contenido |
|---|---|
| `test-signing.jks` | El almacén de claves (keystore) con la clave de firma. |
| `test-signing.password` | Una sola línea con la contraseña del almacén. |

Los nombres son los que usa la guía; puedes usar otros si ajustas las variables de abajo.

## Por qué aquí y no en `secrets/`

`docker-compose.yml` monta `secrets/` dentro del servidor (para las cookies de yt-dlp). La clave de firma no la necesita
ningún contenedor, así que vive en una carpeta que no monta nada. La imagen Docker se construye desde `middleware/`, así
que esta carpeta tampoco entra en ella.

## Crear una clave nueva (si aún no tienes)

```sh
chmod 700 firma-android
keytool -genkeypair -v -keystore firma-android/test-signing.jks -alias armonia \
  -keyalg RSA -keysize 4096 -validity 10000
# escribe la contraseña elegida en una sola línea:
printf '%s\n' 'TU_CONTRASEÑA' > firma-android/test-signing.password   # o con un editor, para no dejarla en el historial
chmod 600 firma-android/*
```

## Usarla al compilar

```sh
export MUSIC_KEYSTORE_FILE="$PWD/firma-android/test-signing.jks"
export MUSIC_KEYSTORE_PASSWORD_FILE="$PWD/firma-android/test-signing.password"
export MUSIC_KEY_ALIAS=armonia            # el alias que pusiste al crearla
python3 tools/android/build_android.py :app:assembleRelease
```

Más detalles en [`docs/ENTORNO.md`](../docs/ENTORNO.md).

## Importante

- **Guarda una copia cifrada fuera del equipo.** Android solo instala una actualización encima de la app si está firmada
  con la misma clave. Si la pierdes, hay que desinstalar la app (y se pierde lo descargado en el móvil).
- **No uses `git clean -x`** en el repositorio: borra los archivos ignorados, y la clave es uno de ellos.
- No la compartas ni la subas a ningún sitio: quien la tenga puede publicar actualizaciones que tu móvil aceptará.
