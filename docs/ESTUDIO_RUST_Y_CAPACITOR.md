# Estudio de Rust y Capacitor para Armonia

Propuesta para evaluar. La revision parte de la [version de Armonia del 23 de noviembre de 2026](https://github.com/davalonie/armonia/tree/2994459).

**Probaria primero una APK con la interfaz Svelte y el reproductor Android actual**, manteniendo FastAPI durante la prueba. Los cambios en portadas, busqueda y cola han requerido trabajo en dos clientes. Compartir las pantallas reduciria ese coste. La decision sobre Rust puede tomarse por separado, cuando sepamos cuanto tiempo, CPU y memoria consume el codigo Python bajo la carga habitual del homelab.

## Una interfaz para el navegador y la APK

La web ya genera `middleware/frontend/dist` con Svelte y Vite. Capacitor puede copiar esa compilacion dentro de la APK. Asi, el telefono puede abrir la interfaz en modo avion y mostrar la musica que tenga guardada. Inicio, Buscar, Biblioteca, playlists y ajustes son buenos candidatos para compartir. El navegador seguiria usando su reproductor HTML. [Guia de instalacion de Capacitor](https://capacitorjs.com/docs/getting-started) · [Reproductor web de Armonia](../middleware/frontend/src/lib/stores/playerStore.js).

**En Android conservaria Media3 y Kotlin.** Armonia ya tiene servicios para reproduccion en segundo plano y descargas, navegacion desde Android Auto, controles de auriculares y cache por cuenta. Un plugin de Capacitor podria conectar las pantallas Svelte con esos servicios. El reproductor nativo seria el responsable de la cola, la posicion y el registro de escuchas. Cuando la interfaz vuelve a abrirse, consulta el estado actual. Asi, un salto de pista desde el coche se refleja al volver al telefono y una escucha se registra una sola vez. [Servicios Android de Armonia](../android/app/src/main/AndroidManifest.xml) · [Plugins nativos de Capacitor](https://capacitorjs.com/docs/plugins/android) · [Reproduccion en segundo plano con Media3](https://developer.android.com/media/media3/session/background-playback).

El coste principal esta en conectar esa interfaz con el dispositivo. Hoy la web usa una cookie y el backend comprueba el origen. La APK permite elegir servidor y protege la sesion con Android Keystore. Empaquetar la web cambia su origen. Para la APK reutilizaria el cliente HTTP nativo y mantendria las credenciales fuera de JavaScript. Tambien habria que mantener el proyecto Gradle, la firma y las actualizaciones de Capacitor y de sus plugins. [Autenticacion del backend](../middleware/auth.py) · [Almacen de sesion Android](../android/app/src/main/java/com/armonia/app/security/SessionVault.kt).

### Prueba que justificaria adoptar Capacitor

Haria un recorrido completo con una sola playlist antes de trasladar el resto de pantallas.

1. Iniciar sesion, abrir la playlist, reproducirla y bloquear el telefono. Avanzar desde los auriculares y confirmar al desbloquear que titulo, posicion y cola coinciden.
2. Buscar y reproducir la playlist desde Android Auto con la interfaz del telefono cerrada. Confirmar que Koito recibe una sola escucha por reproduccion valida.
3. Descargar la playlist, cerrar la app y volver a abrirla en modo avion. Comprobar que aparece en Inicio y que se puede reproducir. Cambiar de cuenta y verificar que la nueva cuenta solo ve sus descargas.
4. Instalar la APK experimental sobre una version de prueba anterior con el mismo identificador y firma. Comprobar que conserva sesion, playlists y descargas. Medir arranque y memoria frente al cliente actual en un telefono de uso habitual.

Si el recorrido funciona y modificar una pantalla compartida simplifica el trabajo, trasladaria las demas por etapas. Si mantener sincronizados Svelte y el servicio nativo exige tanto trabajo como los dos clientes actuales, conservaria la app Kotlin.

## Que puede aportar Rust al backend

Rust podria reducir CPU o memoria en partes del servidor que procesan datos o atienden muchos streams a la vez. Otras operaciones dependen del disco, SQLite, Navidrome o del tiempo de respuesta de YouTube. FFmpeg ya convierte el audio en un proceso externo. Armonia usa `yt-dlp` y `ytmusicapi` directamente desde Python para extraccion y consultas musicales. Un servidor en Rust puede invocar `yt-dlp` por linea de comandos, pero tendria que resolver tambien las busquedas, la cancelacion, los reintentos y el etiquetado. Mantener un trabajador Python junto al servidor Rust añade otro proceso al consumo del homelab. [Codigo de la integracion actual](../middleware/services/ytdlp_service.py) · [yt-dlp](https://github.com/yt-dlp/yt-dlp#embedding-yt-dlp) · [ytmusicapi](https://ytmusicapi.readthedocs.io/en/stable/).

Hay un precedente medido en Armonia. Al retirar la portada incrustada de la cabecera de los MP4, la mediana de datos necesarios para empezar a sonar bajo de **588 KB a 133 KB**. En una red lenta, esos bytes importan aunque el servidor responda enseguida. El laboratorio ya mide el tiempo hasta el primer byte de audio y permite simular un enlace lento. [Medicion documentada](../middleware/services/mp4_light.py) · [Prueba de carga](../tools/lab/medir_carga.py) · [Simulador de red lenta](../tools/lab/camino_lento.py).

Empezaria midiendo memoria en reposo y pico, CPU durante una importacion y tiempo hasta el primer audio, con cache fria y caliente. Usaria las mismas canciones, concurrencia y limites de Docker para ambas versiones. Si el coste se concentra en una funcion Python, probaria una extension Rust con PyO3 dentro del servicio actual. Si afecta a varias rutas, tendria sentido evaluar una API Rust mas amplia. Si el tiempo se va en la red o en FFmpeg, mantendria FastAPI y centraria el trabajo en la causa medida. [PyO3](https://docs.rs/crate/pyo3/latest).

## Como comprobar una reescritura hecha por IA

Anthropic describio como comparo su API de mensajes en Python con una implementacion Rust enviando peticiones a ambas antes de cambiar el trafico. Para Armonia, lo aprovechable es disponer de una referencia ejecutable. La IA puede escribir el port y generar casos adicionales. Conviene acordar antes los resultados esperados y revisar por separado cualquier diferencia que obligue a cambiar una prueba. [Entrevista al equipo, desde el minuto 56](https://latent.space/p/how_anthropic_ships_the_1_llm_in_the_world_safely_separating_the_brain_from_the_hands/) · [Guia de migraciones de Anthropic](https://claude.com/resources/articles/ai-code-migration).

- **Probar desde fuera.** La version revisada pasa 750 pruebas de backend. Sus 60 archivos de pruebas importan modulos de la aplicacion Python. Reutilizaria sus casos para crear un conjunto de peticiones HTTP que se pueda ejecutar sin cambios contra ambos servidores.
- **Aislar los efectos.** Cada servidor tendria su propia copia de SQLite y de la biblioteca ficticia, con respuestas reproducibles de los proveedores. Incluso `GET /api/home/playlists` puede iniciar una actualizacion. Duplicar trafico contra los servicios reales podria enviar dos escuchas a Koito o iniciar dos descargas. [Ruta de Inicio](../middleware/routes/home.py).
- **Comparar lo que importa.** Verificar los bytes devueltos al adelantar una pista, el orden de una importacion reanudada, la ausencia de descargas duplicadas y la revocacion de una sesion durante una operacion. Comparar tambien archivos, etiquetas y cambios en la base de datos. Los identificadores generados pueden diferir si mantienen las mismas relaciones.
- **Decidir con resultados.** Registrar las diferencias intencionadas y medir rendimiento una vez comprobado el comportamiento. Si se despliega Rust por etapas, asignar a una sola version las escrituras de cada operacion y ensayar la vuelta a Python con una copia de la base de datos antes de cambiar el esquema.

## Seguimiento

Si se inicia trabajo, abriria un issue para **probar una playlist en una APK con Capacitor y Media3** y otro para **medir el backend actual y elegir un posible piloto en Rust**. Cada uno se puede cerrar con sus mediciones y una decision, incluida la de mantener la arquitectura actual.
