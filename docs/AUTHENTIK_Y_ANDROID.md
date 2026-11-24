# Acceso con Authentik y prueba de Armonia Capacitor

El Compose habitual admite el acceso con Navidrome. Para añadir el botón **Entrar con Authentik**, activa la configuración siguiente en la instalación que quieras probar. Las dos APK usan un navegador externo y aceptan la URL del servidor en su pantalla de acceso.

## Proveedor y grupo

1. En la administración de Authentik, crea el grupo `armonia` en **Directory → Groups** y añade los usuarios que pueden acceder.
2. En **Applications → Applications → Create with Provider**, crea la aplicación Armonia, slug `armonia`, con un proveedor OAuth2/OpenID. Elige cliente **confidencial**, grant **Authorization Code**, emisor por aplicación y clave de firma RSA para **RS256**. Conserva el identificador de cliente y guarda su secreto en el servidor.
3. Selecciona los mappings **openid** y **profile** e incluye los claims en el ID token. El mapping de perfil debe emitir `groups` como una lista de nombres. Para una instalación nueva, selecciona **User UUID** como modo de subject. Conserva el modo elegido después de vincular usuarios.
4. Registra la URI de redirección **estricta** `https://musica.example/api/oidc/callback`. En la aplicación, abre **Policy / Group / User Bindings**, vincula el grupo `armonia` y comprueba el resultado con un usuario del grupo y otro sin acceso. [Proveedor OIDC y redirecciones de Authentik](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/)

### Configuración del servidor

Guarda el secreto del cliente en `secrets/oidc-client-secret`, legible por el UID del contenedor y con permisos `0600`. En `.env` de la instalación de prueba:

```dotenv
COMPOSE_FILE=docker-compose.yml:compose.authentik.yaml
MUSIC_PUBLIC_ORIGIN=https://musica.example
MUSIC_COOKIE_SECURE=true
MUSIC_OIDC_ISSUER=https://identidad.example/application/o/armonia/
MUSIC_OIDC_CLIENT_ID=armonia
MUSIC_OIDC_GROUP=armonia
```

Usa el valor exacto de `issuer` del documento de descubrimiento, incluida la barra final si la lleva. El backend consulta el descubrimiento y las claves públicas, y canjea el código por HTTPS. El navegador y Armonia necesitan alcanzar el mismo emisor. Si ya usas `compose.metadata.yaml`, conserva ese archivo en `COMPOSE_FILE`. Puedes omitir `MUSIC_OIDC_GROUP` para delegar la comprobación del grupo exclusivamente a Authentik.

El overlay monta el secreto mediante `MUSIC_OIDC_SECRET_FILE` y reserva `10.253.248.2/32` como origen de confianza de Navidrome en la red privada `library`. Si la subred está ocupada, selecciona una libre con `MUSIC_LIBRARY_SUBNET` y una IP de esa subred con `MUSIC_PROXY_IP`. En un Navidrome externo, configura `ExtAuth.UserHeader=X-Armonia-User` y limita `ExtAuth.TrustedSources` a la IP desde la que llega Armonia. El proxy de entrada debe conservar el Host público. [Autenticación externa de Navidrome](https://www.navidrome.org/docs/usage/integration/authentication/)

### Vincular a una cuenta musical existente

El operador verifica la identidad de Authentik y la cuenta musical en sus respectivos paneles. Con **User UUID**, usa el campo `uuid` del usuario de Authentik como subject. Copia el ID nativo de Navidrome del registro del usuario. También aparece como `userId` en `/api/me` al entrar con la cuenta local de Armonia. La siguiente operación requiere la contraseña de esa cuenta una vez, mediante un prompt privado.

```sh
docker compose exec music python -m tools.bind_oidc \
  --subject UUID_DEL_USUARIO_EN_AUTHENTIK \
  --user-id ID_NATIVO_EN_NAVIDROME --username usuario_musical
```

Armonia verifica la contraseña y el ID en Navidrome y guarda la asociación única `(issuer, subject) → user_id` en su propia SQLite. Guarda cifrada la credencial derivada de Subsonic. El aprovisionamiento conecta también la cuenta de Aurral ya asignada en el stack. Para cuentas de Aurral con credenciales independientes, completa la vinculación habitual una vez en **Ajustes → Recomendaciones**. Koito se selecciona por el ID musical y usa el token privado que se configuró para esa cuenta. El alta de usuarios musicales sigue a cargo del administrador. Una identidad OIDC sin asociación recibe una denegación.

En cada entrada por Authentik, Armonia consulta `/api/user/{id}` con la cabecera privada y comprueba ID, usuario, bibliotecas y rol actuales. Comprueba con un ping que la credencial individual sigue siendo válida. Las peticiones de música siguen usando ese par Subsonic individual, también en operaciones en segundo plano. Navidrome invalida ese par cuando cambia la contraseña musical. En ese caso, repite el comando de vinculación para renovar el par. En Navidrome 0.64.2 también comprobamos por proxy `ping`, `getUser`, `getMusicFolders`, `getPlaylists`, `getPlaylist` y `stream` con rango. La credencial individual permite que el mismo código de biblioteca, descargas y tareas de fondo funcione con los dos métodos de acceso. [Implementación de autenticación en Navidrome 0.64.2](https://github.com/navidrome/navidrome/blob/v0.64.2/server/auth.go)

### Retornos de los clientes

| Cliente | Retorno |
| --- | --- |
| Authentik a Armonia, para los tres clientes | `https://musica.example/api/oidc/callback` |
| Web después de aceptar el código | `https://musica.example/?oidc=done` |
| APK Kotlin release / debug | `io.github.davalonie.armonia://oidc/callback` / `io.github.davalonie.armonia.debug://oidc/callback` |
| APK Capacitor release / debug | `io.github.davalonie.armonia.capacitor://oidc/callback` / `io.github.davalonie.armonia.capacitor.debug://oidc/callback` |

En Authentik solo se registra el retorno HTTPS al servidor. La transacción dura diez minutos, usa state, nonce, PKCE S256 y una cookie temporal HttpOnly SameSite=Lax ligada al navegador. La sesión web sigue en una cookie HttpOnly SameSite=Strict y las operaciones conservan las comprobaciones de origen y de propietario. Android recibe un código intermedio de un uso, válido durante 90 segundos. Solo la APK que generó el verificador puede canjearlo en el servidor elegido. El verificador pendiente y la sesión se cifran con Android Keystore. Al personalizar `-PmusicApplicationId`, configura el mismo identificador base en `MUSIC_ANDROID_APPLICATION_ID` en el servidor.

Salir desde Armonia revoca la sesión de Armonia. Authentik mantiene su propia sesión de navegador y puede reutilizarla en el siguiente acceso. Para elegir otra identidad SSO, cambia de usuario en Authentik o cierra allí la sesión.

## Las dos compilaciones

Con el SDK y JDK de [la guía del entorno](ENTORNO.md), ejecuta desde la raíz:

```sh
(cd middleware/frontend && npm ci --ignore-scripts --no-audit --no-fund)
android/gradlew -p android :app:assembleDebug :app:testDebugUnitTest
android/gradlew -p android-capacitor :app:assembleDebug :app:assembleDebugAndroidTest
```

Gradle compila Svelte en modo `capacitor` y empaqueta el resultado en `assets/public` de la APK experimental. Usa el wrapper del cliente Kotlin para ambos proyectos. Las APK quedan en `android/app/build/outputs/apk/debug/app-debug.apk` y `android-capacitor/app/build/outputs/apk/debug/app-debug.apk`. El nombre visible experimental añade **Capacitor** y el ID añade `.capacitor` antes del sufijo de debug. Las actualizaciones requieren el mismo identificador y clave de firma.

El teléfono abre los recursos locales y muestra sus descargas en **Inicio → En el teléfono**. Las pantallas Svelte usan el cliente HTTP nativo con la sesión de esa cuenta. Cada servidor y usuario dispone de un origen local distinto en el WebView. La cola, la posición, el audio, el catálogo descargado, las escuchas y el servicio de Android Auto pertenecen al reproductor Kotlin compartido. El navegador de escritorio y el móvil web conservan el reproductor HTML.

### Recorrido de cinco minutos

1. Instala ambas APK con `adb install -r` y comprueba que aparecen **Armonia** y **Armonia Capacitor**. En la experimental escribe la URL del servidor y pulsa **Entrar con Authentik**.
2. En **Biblioteca → Playlists**, abre una lista corta, pulsa **Descargar playlist** y espera al contador completo. Pulsa **Reproducir**, bloquea el teléfono y avanza desde la notificación. Al volver, comprueba título, posición y cola.
3. Cierra la app, activa el modo avión y vuelve a abrir **Armonia Capacitor**. Encuentra la playlist en **Inicio → En el teléfono**, abre sus pistas y reprodúcelas. Restablece la conexión.
4. En **Más → Ajustes**, sal y entra con la segunda cuenta. Comprueba sus playlists, historial y descargas. Abre **Armonia** desde el otro icono y verifica su sesión independiente.
5. Si la APK de prueba no aparece en el coche, activa **Orígenes desconocidos** en los ajustes de desarrollador de Android Auto. Con Android Auto conectado y la interfaz del teléfono cerrada, elige **Armonia Capacitor → Playlists** y reproduce una pista de al menos 30 segundos. Deja sonar más de la mitad para una pista corta. Comprueba su aparición en el historial de la cuenta. [Pruebas de aplicaciones multimedia en Android Auto](https://developer.android.com/training/cars/testing#unknown-sources)

### Paridad funcional de Kotlin y Capacitor

Kotlin es la referencia. Capacitor conserva su botón de reproducción morado (`#c4a3ff`). Ambas APK usan el mismo servicio Media3, la misma caché de audio y el mismo cargador Coil, cada una con su propio almacenamiento. Las pruebas del 24 de noviembre de 2026 usaron un emulador Android 15, dos cuentas de laboratorio y un servidor Navidrome.

| Función | Resultado observado |
| --- | --- |
| Caché de canciones y portadas | Una escucha de 55 s quedó disponible sin marcar descarga. Después de cerrar el proceso y activar modo avión se reprodujo desde disco. La portada reapareció y el servidor recibió cero peticiones nuevas de audio o imagen. Con datos móviles, una portada nueva se pidió a 600 px y se reutilizó la de 1024 px descargada por Wi-Fi. |
| Calidad con conexión lenta | Con el ahorro manual desactivado y el caudal limitado a 112 kbit/s, Android estimó 159 kbit/s y reprodujo la siguiente pista con la variante de ahorro. En la primera pasada se verificó el audio servido, Opus a 64,4 kbit/s. |
| Precarga por Wi-Fi | Se añadió a favoritos una pista sin escuchar. Se adelantó la ejecución del trabajo periódico con el planificador de Android. Descargó 590.612 bytes y la canción apareció entre las disponibles sin conexión. |
| Descargas | Se guardó y retiró una canción desde el reproductor. Se descargó una playlist de dos pistas, se retiró solo esa lista y la otra descarga siguió completa. La app distingue una descarga individual de una canción guardada con un álbum o playlist. |
| Playlists mixtas | Una lista mixta de dos pistas locales se descargó desde su ficha y se reprodujo sin servidor después de cerrar la app. Se probó una segunda lista con una pista que permitía solo streaming. El teléfono explicó la restricción y evitó crear una descarga parcial. Retirar la primera lista conservó la otra colección que compartía las pistas. |
| Biblioteca sin servidor | Se desconectó el túnel al servidor y se reinició el proceso. La pestaña habitual de playlists mostró la lista y el detalle conservó los títulos en su último orden. «En el teléfono» permite reproducir las pistas disponibles. |
| Reproducción y cola | Se activó y canceló el temporizador y se comprobó la pausa al finalizar la canción. Añadir a continuación, añadir a la cola y añadir al final conservan posiciones distintas. «Deshacer» retiró solo la copia recién insertada. Se probaron el salto por toque, la reordenación, los gestos de añadir y quitar, el orden aleatorio de Media3 y la navegación al artista. La preescucha de diez segundos devolvió la cola que estaba sonando. |
| Edición de playlists | Desde la pantalla de una lista se abrió el editor de Kotlin, se añadió una canción y se cambió su posición. Se seleccionó un PNG con el selector de Android. Navidrome devolvió la portada personalizada y el orden nuevos. |
| Importación desde archivos de Spotify | Desde la APK se importó un CSV y se verificaron las dos pistas y su orden en Navidrome. La importación múltiple abrió el navegador de Android. Un ZIP de Exportify con dos listas se importó en el navegador del laboratorio y se cotejó el contenido de ambas en Navidrome. Estas pruebas se hicieron con archivos exportados, sin iniciar sesión en una cuenta real de Spotify. |
| MP3 pendiente de añadir | Se abrió una referencia de prueba, se eligió un MP3 desde «Descargas» en el selector de Android y se guardó desde la APK. Tras el escaneo, Navidrome devolvió el identificador de la canción con el título y artista correctos. |
| Cuentas y controles de Android | Al cambiar de usuario, la segunda cuenta mostró su propio historial, sin la cola ni las descargas de la primera. Al volver con Authentik se recuperó la playlist descargada 2/2. Con la pantalla bloqueada, el control de Android avanzó a la siguiente pista y la app mostró la misma cola al desbloquear. |
| Pantallas y ajustes | Se recorrieron Inicio, Biblioteca, Buscar, Más, álbumes, artistas, favoritos, importación, historial y ajustes. Se comprobó el color del botón de reproducción, el cambio de fuente de búsqueda y la persistencia del ahorro de datos en las preferencias Android. |

En una prueba anterior con el Galaxy A55 también se reprodujo una playlist descargada en modo avión, se cambió de pista con la pantalla bloqueada y se navegó y reprodujo desde Android Auto con el Desktop Head Unit. En esta ronda también se verificó en el emulador que el cliente multimedia de Android puede explorar la biblioteca y reproducir una playlist con Armonía cerrada. Koito registró una escucha nueva en la cuenta que reprodujo la música y la otra cuenta conservó su historial.

La prueba de instrumentación `CarLibraryTest` comprueba el catálogo con el navegador multimedia clásico de Android y la reproducción con Media3. Acepta el argumento `playlist` con el nombre de una lista del laboratorio y requiere una sesión ya iniciada.
