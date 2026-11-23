# Acceso y archivos de la biblioteca

Armonia autentica las cuentas a traves de Navidrome. Asigna a cada cuenta su biblioteca antes de importar musica. Tanto el servidor como Navidrome deben ver los mismos archivos en sus respectivos montajes.

El servidor escribe los archivos descargados en un directorio temporal y vuelve a comprobar los permisos antes de incorporarlos a la biblioteca. Para borrar canciones hacen falta una cuenta administradora de Navidrome y una autorizacion explicita en `MUSIC_DELETE_USERS`. La lista de autorizaciones esta vacia de forma predeterminada.

La web y Android utilizan la API publica del servidor. El puerto interno 8001 se reserva para las integraciones del stack. El Compose local publica la web en la interfaz de bucle local. Configura HTTPS en el punto de acceso de tu instalacion para abrir la biblioteca desde otros dispositivos.

Conserva por separado las claves de la instalacion y la musica. Los directorios `runtime/` y `secrets/` contienen estado privado. Incluye estos datos en tus copias de seguridad y comprueba su restauracion antes de cambiar de servidor.
