# firma-android

Esta carpeta guarda **tu** clave de firma de la app Android. Git solo sigue este README: los archivos de clave estan
excluidos en `.gitignore` y nunca se suben.

## Que va aqui

| Archivo | Contenido |
|---|---|
| `test-signing.jks` | El almacen de claves (keystore) con la clave de firma. |
| `test-signing.password` | Una sola linea con la contraseña del almacen. |

Los nombres son los que usa la guia; puedes usar otros si ajustas las variables de abajo.

## Por que aqui y no en `secrets/`

El stack completo monta los secretos de cada servicio por separado. El Compose minimo monta `secrets/` dentro del
servidor para las cookies de yt-dlp. La clave de firma vive en un directorio exclusivo de la compilacion Android.

## Crear una clave nueva (si aun no tienes)

```sh
chmod 700 firma-android
keytool -genkeypair -v -keystore firma-android/test-signing.jks -alias armonia \
  -keyalg RSA -keysize 4096 -validity 10000
# escribe la contraseña elegida en una sola linea:
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

Mas detalles en [`docs/ENTORNO.md`](../docs/ENTORNO.md).

## Importante

- **Guarda una copia cifrada fuera del equipo.** Android solo instala una actualizacion encima de la app si esta firmada
  con la misma clave. Si la pierdes, hay que desinstalar la app (y se pierde lo descargado en el movil).
- **No uses `git clean -x`** en el repositorio: borra los archivos ignorados, y la clave es uno de ellos.
- No la compartas ni la subas a ningun sitio: quien la tenga puede publicar actualizaciones que tu movil aceptara.
