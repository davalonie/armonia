package com.armonia.app.ui.playlists

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.homelab.*
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.*
import javax.inject.Inject

@HiltViewModel
class ManualInboxViewModel @Inject constructor(
    private val api: MusicApi,
    private val prefs: PreferencesRepository,
    @ApplicationContext private val context: Context,
) : ViewModel() {
    private val account = prefs.cachedAuth
    private var operation: Job? = null
    private var uploadBody: BoundedMp3Body? = null
    var entries by mutableStateOf<List<ManualInboxItem>>(emptyList()); private set
    var busy by mutableStateOf(false); private set
    var error by mutableStateOf<String?>(null); private set
    var notice by mutableStateOf<String?>(null); private set

    init {
        viewModelScope.launch {
            prefs.authState.collect { current ->
                if (!manualUploadAccountMatches(account, current)) {
                    uploadBody?.close(); operation?.cancel(); entries = emptyList()
                    error = "La cuenta o la sesión ha cambiado. Vuelve a abrir esta pantalla."
                }
            }
        }
        refresh()
    }

    private fun currentAccount() = manualUploadAccountMatches(account, prefs.cachedAuth)
    private fun requireAccount() {
        if (!currentAccount()) throw ManualInboxFailure("La cuenta o la sesión ha cambiado. Vuelve a abrir esta pantalla.")
    }
    private suspend fun load() {
        requireAccount()
        val result = api.manualInbox(account).checkedInbox()
        requireAccount()
        entries = result.items
    }
    private fun act(work: suspend () -> Unit) {
        if (busy) return
        busy = true; error = null; notice = null
        operation = viewModelScope.launch {
            try { requireAccount(); work() }
            catch (e: TimeoutCancellationException) { error = "La subida ha tardado demasiado. Actualiza la bandeja para comprobar si el archivo llegó a guardarse." }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                if (currentAccount()) error = (e as? ManualInboxFailure)?.userMessage
                    ?: "No se pudo completar la operación. Actualiza la bandeja antes de reintentar."
                else { entries = emptyList(); error = "La sesión ha cambiado. Vuelve a abrir esta pantalla." }
            } finally { uploadBody?.close(); uploadBody = null; busy = false }
        }
    }
    fun refresh() = act { load() }
    fun fileSelectionUnavailable() { error = "Actualiza la bandeja y vuelve a seleccionar el archivo para este pendiente." }
    fun refreshItem(item: ManualInboxItem) = act {
        api.refreshManualInbox(item.id, ManualInboxRevision(item.revision), account).checkedInbox()
        load()
    }
    fun remove(item: ManualInboxItem) = act {
        api.removeManualInbox(item.id, ManualInboxRevision(item.revision), account).checkedInbox()
        load()
        notice = "Referencia retirada de la bandeja. La música y las playlists se conservan."
    }
    fun upload(item: ManualInboxItem, uri: Uri) = act {
        if (uri.scheme != "content") throw ManualInboxFailure("Selecciona el archivo con el selector de documentos.")
        if (entries.none { it.id == item.id && it.revision == item.revision && it.status == "pending" })
            throw ManualInboxFailure("El pendiente ha cambiado. Actualiza antes de aportar el archivo.")
        val resolver = context.contentResolver
        val knownSize = withContext(Dispatchers.IO) {
            resolver.query(uri, arrayOf(OpenableColumns.SIZE), null, null, null)?.use { cursor ->
                if (!cursor.moveToFirst() || cursor.isNull(0)) null else cursor.getLong(0).takeIf { it >= 0 }
            }
        }
        requireAccount()
        val body = BoundedMp3Body(
            open = { resolver.openInputStream(uri) ?: throw ManualInboxFailure("No se pudo abrir el archivo seleccionado.") },
            stillAuthorized = ::currentAccount,
            declaredSize = knownSize,
        )
        uploadBody = body
        // Receiving can take 180 s, decoding 120 s and library indexing 8 s.
        withTimeout(330_000) { api.uploadManualInbox(item.id, item.revision, body, account).checkedInbox() }
        load()
        notice = "Archivo guardado en tu biblioteca. Desde allí puedes añadirlo a la playlist que quieras."
    }
    fun cancel() {
        uploadBody?.close()
        operation?.cancel()
        notice = "Operación interrumpida. Actualiza la bandeja para comprobar si el archivo llegó a guardarse."
    }
    override fun onCleared() {
        uploadBody?.close()
        super.onCleared()
    }
}

@Composable
fun ManualInboxScreen(onBack: () -> Unit, onLibrary: () -> Unit, vm: ManualInboxViewModel = hiltViewModel()) {
    var selectedId by rememberSaveable { mutableStateOf<String?>(null) }
    var selectedRevision by rememberSaveable { mutableStateOf<Int?>(null) }
    var removing by remember { mutableStateOf<ManualInboxItem?>(null) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        val entry = vm.entries.firstOrNull { it.id == selectedId && it.revision == selectedRevision }
        selectedId = null; selectedRevision = null
        if (uri != null) {
            if (entry != null && !vm.busy) vm.upload(entry, uri)
            else vm.fileSelectionUnavailable()
        }
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            TextButton(onClick = onBack) { Text("← Biblioteca") }
            Text("Pendientes de añadir", style = MaterialTheme.typography.headlineMedium)
            Text("Aquí se guardan las canciones que has omitido al importar. Aporta un MP3 propio cuando lo tengas; no se descarga nada desde Spotify.")
            Text("El archivo se guardará en tu biblioteca. Después puedes añadirlo a cualquier playlist desde Biblioteca.")
            Text("Se guardará una copia MP3 a 192 kb/s; el archivo original de tu dispositivo se conserva.")
            Text("MP3 de hasta 64 MiB.", style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = vm::refresh, enabled = !vm.busy) { Text("Actualizar") }
            if (vm.busy) {
                LinearProgressIndicator(Modifier.fillMaxWidth())
                TextButton(onClick = vm::cancel) { Text("Cancelar operación") }
            }
            vm.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            vm.notice?.let { Text(it) }
            if (!vm.busy && vm.entries.isEmpty() && vm.error == null) Text("No tienes canciones pendientes.")
        }
        items(vm.entries, key = { it.id }) { entry ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(entry.track.title, style = MaterialTheme.typography.titleMedium)
                    Text(entry.track.artist)
                    Text("De ${entry.originName}", style = MaterialTheme.typography.bodySmall)
                    when (entry.status) {
                        "pending" -> Button(enabled = !vm.busy, onClick = {
                            selectedId = entry.id; selectedRevision = entry.revision
                            picker.launch(arrayOf("audio/mpeg", "audio/mp3"))
                        }) { Text("Aportar MP3") }
                        "saved" -> {
                            if (entry.songId == null) {
                                Text("El archivo está guardado; la biblioteca aún no lo encuentra.")
                                TextButton(enabled = !vm.busy, onClick = { vm.refreshItem(entry) }) { Text("Comprobar biblioteca") }
                            } else {
                                Text("Ya está en tu biblioteca.")
                                TextButton(onClick = onLibrary) { Text("Ver biblioteca") }
                            }
                        }
                        else -> Text("Actualiza la bandeja para comprobar el estado.")
                    }
                    TextButton(enabled = !vm.busy, onClick = { removing = entry }) { Text("Retirar de pendientes") }
                }
            }
        }
    }
    removing?.let { entry ->
        AlertDialog(onDismissRequest = { removing = null }, title = { Text("Retirar referencia") },
            text = { Text("Se retirará «${entry.track.title}» de esta bandeja. No se borrará ningún archivo musical ni se modificará ninguna playlist.") },
            confirmButton = { TextButton(onClick = { removing = null; vm.remove(entry) }) { Text("Retirar") } },
            dismissButton = { TextButton(onClick = { removing = null }) { Text("Cancelar") } })
    }
}
