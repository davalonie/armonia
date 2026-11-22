package com.armonia.app.ui.components

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DownloadDone
import androidx.compose.material.icons.filled.DownloadForOffline
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.armonia.app.offline.OfflineProgress

/**
 * Starts or removes a download to the phone. Downloads run in a foreground service whose progress
 * notification needs POST_NOTIFICATIONS on Android 13+: ask on the first one; the download runs
 * either way, the notification is just hidden if it is declined.
 */
@Composable
fun rememberOfflineToggle(isPinned: Boolean, onToggle: () -> Unit): () -> Unit {
    val context = LocalContext.current
    val askPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { onToggle() }
    return {
        val needsPrompt = !isPinned && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        if (needsPrompt) askPermission.launch(Manifest.permission.POST_NOTIFICATIONS) else onToggle()
    }
}

/** "Guardar sin conexión" toggle with download progress, shown under Play/Shuffle on album pages. */
@Composable
fun KeepOfflineRow(
    isPinned: Boolean,
    progress: OfflineProgress?,
    onToggle: () -> Unit,
) {
    val start = rememberOfflineToggle(isPinned, onToggle)
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        TextButton(onClick = start) {
            when {
                !isPinned -> {
                    Icon(Icons.Default.DownloadForOffline, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("Guardar sin conexión")
                }
                progress?.running == true -> {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                    Text("Descargando ${progress.done}/${progress.total}")
                }
                else -> {
                    Icon(Icons.Default.DownloadDone, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                    Spacer(Modifier.width(8.dp))
                    Text(if ((progress?.failed ?: 0) > 0) "En el teléfono (${progress!!.failed} con error)" else "Guardado sin conexión")
                }
            }
        }
        if (isPinned) {
            Spacer(Modifier.weight(1f))
            Text(
                text = "Toca para quitar",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f),
            )
        }
    }
}
