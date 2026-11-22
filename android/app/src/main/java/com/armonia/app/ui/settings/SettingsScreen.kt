package com.armonia.app.ui.settings

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import com.armonia.app.R
import com.armonia.app.data.api.StatsResponse

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onLogout: () -> Unit,
    viewModel: SettingsViewModel = hiltViewModel(),
) {
    var showLogoutDialog by remember { mutableStateOf(false) }

    Scaffold(
        contentWindowInsets = WindowInsets(0),
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            painter = painterResource(id = R.drawable.ic_armonia),
                            contentDescription = null,
                            modifier = Modifier.size(40.dp),
                            tint = Color.Unspecified
                        )
                        Spacer(Modifier.width(6.dp))
                        Text("Ajustes", color = Color.White, style = MaterialTheme.typography.headlineMedium)
                    }
                },
                actions = {
                    IconButton(onClick = { viewModel.loadStats() }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Actualizar")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            // ── Reproducción ─────────────────────────────────────────────────
            SectionCard(title = "Reproducción") {
                val continueSimilar by viewModel.continueSimilar.collectAsState()
                LaunchedEffect(Unit) { viewModel.musicPlayer.refreshPlaybackSettings() }
                Row(
                    modifier = Modifier.fillMaxWidth().padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Continuar con música similar", style = MaterialTheme.typography.bodyLarge)
                        Text(
                            text = if (continueSimilar) "Cuando termina lo que has elegido, siguen sonando canciones relacionadas."
                                   else "Desactivado: la reproducción se detiene al terminar la cola.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                        )
                        viewModel.playbackSettingError?.let {
                            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                        }
                    }
                    Spacer(Modifier.width(12.dp))
                    Switch(
                        checked = continueSimilar,
                        enabled = !viewModel.savingPlaybackSetting,
                        onCheckedChange = { viewModel.setContinueSimilar(it) },
                    )
                }
            }

            // ── Server stats ─────────────────────────────────────────────────
            SectionCard(title = "Servidor") {
                when {
                    viewModel.statsLoading -> Box(
                        modifier = Modifier.fillMaxWidth().padding(16.dp),
                        contentAlignment = Alignment.Center,
                    ) { CircularProgressIndicator() }
                    viewModel.statsError != null -> Text(
                        text = viewModel.statsError!!,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(16.dp),
                    )
                    viewModel.stats != null -> StatsSection(viewModel.stats!!)
                }
            }

            // ── Search source ────────────────────────────────────────────────
            SectionCard(title = "Buscar") {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "Dónde buscar y de dónde descargar música.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                    )
                    Spacer(Modifier.height(12.dp))
                    val sources = listOf("youtube_music" to "YouTube Music", "youtube" to "YouTube")
                    SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                        sources.forEachIndexed { index, (value, label) ->
                            SegmentedButton(
                                selected = viewModel.searchSource == value,
                                onClick = { viewModel.updateSearchSource(value) },
                                shape = SegmentedButtonDefaults.itemShape(index, sources.size),
                                label = { Text(label, fontSize = 12.sp) },
                            )
                        }
                    }
                }
            }

            // ── Library ──────────────────────────────────────────────────────
            SectionCard(title = "Biblioteca") {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "Lanza un escaneo de la biblioteca de Navidrome para incorporar las canciones recién descargadas.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                    )
                    Spacer(Modifier.height(12.dp))
                    Button(
                        onClick = { viewModel.rescan() },
                        enabled = !viewModel.rescanLoading,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        if (viewModel.rescanLoading) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(18.dp),
                                strokeWidth = 2.dp,
                                color = MaterialTheme.colorScheme.onPrimary,
                            )
                            Spacer(Modifier.width(8.dp))
                        }
                        Text("Escanear biblioteca")
                    }
                    viewModel.rescanMessage?.let { msg ->
                        Spacer(Modifier.height(8.dp))
                        Text(
                            text = msg,
                            style = MaterialTheme.typography.bodySmall,
                            color = if (msg.startsWith("Biblioteca")) MaterialTheme.colorScheme.primary
                                    else MaterialTheme.colorScheme.error,
                        )
                    }
                }
            }

            // ── Streaming cache ───────────────────────────────────────────────
            SectionCard(title = "Caché de reproducción") {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "Las canciones que escuchas se guardan en este teléfono, así que volver a escucharlas no gasta datos.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                    )
                    Spacer(Modifier.height(12.dp))
                    Text(
                        text = "Usando ${formatBytes(viewModel.cacheUsedBytes)} de ${formatMb(viewModel.cacheMaxMb)}",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(Modifier.height(12.dp))
                    val limits = listOf(1024L, 2048L, 4096L, 8192L)
                    SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                        limits.forEachIndexed { index, mb ->
                            SegmentedButton(
                                selected = viewModel.cacheMaxMb == mb,
                                onClick = { viewModel.updateCacheMaxMb(mb) },
                                shape = SegmentedButtonDefaults.itemShape(index, limits.size),
                                label = { Text(formatMb(mb), fontSize = 11.sp) },
                            )
                        }
                    }
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = "El nuevo límite se aplica la próxima vez que abras la aplicación.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                    )
                    Spacer(Modifier.height(12.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("Guardar con Wi‑Fi lo que más escuchas", style = MaterialTheme.typography.bodyMedium)
                            Spacer(Modifier.height(4.dp))
                            Text(
                                text = "Con Wi‑Fi, la semanal, tus favoritas y las más escuchadas se guardan en el " +
                                    "teléfono, así con datos suenan sin gastarlos. Usa como mucho el 40 % de la caché.",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                            )
                        }
                        Spacer(Modifier.width(12.dp))
                        Switch(checked = viewModel.keepOnWifi, onCheckedChange = viewModel::updateKeepOnWifi)
                    }
                    Spacer(Modifier.height(12.dp))
                    OutlinedButton(
                        onClick = { viewModel.clearCache() },
                        enabled = !viewModel.cacheClearing,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(if (viewModel.cacheClearing) "Vaciando…" else "Vaciar caché")
                    }
                    Spacer(Modifier.height(16.dp))
                    Text(
                        text = "Música sin conexión (álbumes y playlists que has guardado): " +
                            "${viewModel.offlineCollections} guardadas, ${formatBytes(viewModel.offlineUsedBytes)}. " +
                            "Esto nunca se borra automáticamente. Las descargas solo se hacen con Wi‑Fi.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(
                        onClick = { viewModel.removeAllOffline() },
                        enabled = viewModel.offlineCollections > 0,
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text("Quitar toda la música sin conexión") }
                }
            }

            // ── Data saving ─────────────────────────────────────────────────
            SectionCard(title = "Ahorro de datos") {
                Column(modifier = Modifier.padding(16.dp)) {
                    val choices = com.armonia.app.playback.DataSaver.entries
                    val labels = mapOf(
                        com.armonia.app.playback.DataSaver.NO to "No",
                        com.armonia.app.playback.DataSaver.DATOS to "Con datos",
                        com.armonia.app.playback.DataSaver.SIEMPRE to "Siempre",
                    )
                    SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                        choices.forEachIndexed { index, choice ->
                            SegmentedButton(
                                selected = viewModel.dataSaver == choice,
                                onClick = { viewModel.updateDataSaver(choice) },
                                shape = SegmentedButtonDefaults.itemShape(index, choices.size),
                                label = { Text(labels.getValue(choice), fontSize = 12.sp) },
                            )
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = "Las canciones llegan a 64 kbps, la mitad de datos. Con mala conexión se usa " +
                            "siempre, para que empiecen antes y no se corten. Lo que ya está en el teléfono suena " +
                            "desde ahí, sin gastar nada. Con datos móviles, además, nunca se adelantan más de 30 s " +
                            "de canción y las carátulas grandes llegan a tamaño medio.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                    )
                    viewModel.dataUsage?.let { usage ->
                        Spacer(Modifier.height(12.dp))
                        Text(
                            text = "Este mes Armonía ha gastado ${formatBytes(usage.mobileBytes)} de datos móviles " +
                                "y ${formatBytes(usage.wifiBytes)} de Wi‑Fi.",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
            }

            // ── Android Auto ─────────────────────────────────────────────────
            SectionCard(title = "Android Auto") {
                AndroidAutoSection(viewModel)
            }

            // ── Account ──────────────────────────────────────────────────────
            SectionCard(title = "Cuenta") {
                Column(modifier = Modifier.padding(16.dp)) {
                    when (viewModel.linked) {
                        true -> Text("Recomendaciones: vinculadas")
                        false -> {
                            var name by remember { mutableStateOf("") }
                            var password by remember { mutableStateOf("") }
                            OutlinedTextField(name, { name = it }, label = { Text("Usuario Aurral") }, singleLine = true)
                            OutlinedTextField(password, { password = it }, label = { Text("Contraseña Aurral") },
                                singleLine = true, visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation())
                            Button(onClick = { viewModel.link(name, password); password = "" },
                                enabled = !viewModel.linking && name.isNotBlank() && password.isNotBlank()) { Text("Vincular") }
                        }
                        null -> if (viewModel.linkError) TextButton(onClick = { viewModel.refreshLink() }) {
                            Text("Reintentar consulta de recomendaciones")
                        } else Text("Consultando recomendaciones…")
                    }
                    if (viewModel.linkError && viewModel.linked == false) Text("No se pudo vincular la cuenta")

                    OutlinedButton(
                        onClick = { showLogoutDialog = true },
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.outlinedButtonColors(
                            contentColor = MaterialTheme.colorScheme.error,
                        ),
                    ) {
                        Text("Cerrar sesión")
                    }
                }
            }

            // ── About ────────────────────────────────────────────────────────
            Box(
                modifier = Modifier.fillMaxWidth().padding(top = 16.dp, bottom = 16.dp),
                contentAlignment = Alignment.Center
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Image(
                        painter = painterResource(id = R.drawable.ic_armonia),
                        contentDescription = null,
                        modifier = Modifier.size(64.dp)
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = com.armonia.app.BuildConfig.APP_NAME,
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
                    )
                    Text(
                        text = "Version ${com.armonia.app.BuildConfig.VERSION_NAME}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.4f)
                    )
                }
            }
        }
    }

    if (showLogoutDialog) {
        AlertDialog(
            onDismissRequest = { showLogoutDialog = false },
            title = { Text("¿Cerrar sesión?") },
            text = { Text("Tendrás que volver a iniciar sesión para usar ${com.armonia.app.BuildConfig.APP_NAME}.") },
            confirmButton = {
                TextButton(onClick = {
                    showLogoutDialog = false
                    viewModel.logout(onLogout)
                }) { Text("Cerrar sesión", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = {
                TextButton(onClick = { showLogoutDialog = false }) { Text("Cancelar") }
            },
        )
    }
}

@Composable
private fun StatsSection(stats: StatsResponse) {
    Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        StatRow(label = "Disco", used = stats.disk.used, total = stats.disk.total)
        StatRow(label = "RAM", used = stats.ram.used, total = stats.ram.total)
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("CPU", style = MaterialTheme.typography.bodyMedium)
            Text(
                text = "%.1f%%".format(stats.cpuPercent),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.primary,
            )
        }
    }
}

@Composable
private fun StatRow(label: String, used: Long, total: Long) {
    val fraction = if (total > 0) used.toFloat() / total.toFloat() else 0f
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(label, style = MaterialTheme.typography.bodyMedium)
            Text(
                text = "${formatBytes(used)} / ${formatBytes(total)}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
            )
        }
        LinearProgressIndicator(
            progress = { fraction },
            modifier = Modifier.fillMaxWidth(),
            color = MaterialTheme.colorScheme.primary,
            trackColor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.1f),
        )
    }
}

@Composable
private fun AndroidAutoSection(viewModel: SettingsViewModel) {
    val context = LocalContext.current
    val connections by viewModel.autoConnections.collectAsState()
    // Re-check whenever the user comes back, e.g. from the battery settings.
    androidx.lifecycle.compose.LifecycleResumeEffect(Unit) {
        viewModel.refreshBatteryState()
        onPauseOrDispose { }
    }
    val muted = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
    Column(modifier = Modifier.padding(16.dp)) {
        Text(
            "Android Auto solo muestra ${com.armonia.app.BuildConfig.APP_NAME} mientras «Fuentes desconocidas» esté activado en los ajustes de " +
                "desarrollador de Android Auto, y vuelve a comprobarlo después de cada actualización.",
            style = MaterialTheme.typography.bodySmall,
            color = muted,
        )
        Spacer(Modifier.height(12.dp))
        val (ok, label) = when {
            viewModel.backgroundRestricted -> false to "El uso en segundo plano de ${com.armonia.app.BuildConfig.APP_NAME} está restringido, así que Android Auto quizá no pueda iniciarla."
            viewModel.batteryOptimized -> false to "La optimización de batería está activada y Android puede detener ${com.armonia.app.BuildConfig.APP_NAME} en segundo plano. Pon Batería en «Sin restricciones»."
            else -> true to "Batería: sin restricciones"
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                if (ok) Icons.Default.CheckCircle else Icons.Default.Warning,
                contentDescription = null,
                tint = if (ok) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(8.dp))
            Text(label, style = MaterialTheme.typography.bodyMedium)
        }
        if (!ok) {
            Spacer(Modifier.height(8.dp))
            OutlinedButton(
                onClick = { runCatching { context.startActivity(viewModel.appSettingsIntent()) } },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Abrir los ajustes de ${com.armonia.app.BuildConfig.APP_NAME}") }
        }
        Spacer(Modifier.height(16.dp))
        Text("Conexiones recientes", style = MaterialTheme.typography.titleSmall)
        Spacer(Modifier.height(4.dp))
        if (connections.isEmpty()) {
            Text(
                "Todavía ninguna. Tras un trayecto en el que ${com.armonia.app.BuildConfig.APP_NAME} no aparecía, mira aquí: si Android Auto no figura " +
                    "a esa hora, es que Android Auto no llegó a pedírsela a ${com.armonia.app.BuildConfig.APP_NAME}.",
                style = MaterialTheme.typography.bodySmall,
                color = muted,
            )
        } else {
            val fmt = remember { java.text.SimpleDateFormat("EEE d MMM, HH:mm", java.util.Locale.getDefault()) }
            connections.take(8).forEach { e ->
                Text(
                    "${fmt.format(java.util.Date(e.timeMillis))} · ${com.armonia.app.auto.controllerLabel(e.packageName)} ${e.event}",
                    style = MaterialTheme.typography.bodySmall,
                    color = muted,
                    modifier = Modifier.padding(vertical = 2.dp),
                )
            }
        }
    }
}

private fun formatMb(mb: Long): String =
    if (mb >= 1024) "${mb / 1024} GB" else "$mb MB"

@Composable
private fun SectionCard(title: String, content: @Composable () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column {
            Text(
                text = title,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
            )
            HorizontalDivider(color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.08f))
            content()
        }
    }
}

private fun formatBytes(bytes: Long): String {
    if (bytes < 1024) return "$bytes B"
    val kb = bytes / 1024.0
    if (kb < 1024) return "%.1f KB".format(kb)
    val mb = kb / 1024.0
    if (mb < 1024) return "%.1f MB".format(mb)
    val gb = mb / 1024.0
    return "%.1f GB".format(gb)
}
