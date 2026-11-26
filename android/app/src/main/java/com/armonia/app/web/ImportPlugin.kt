package com.armonia.app.web

import android.app.Activity
import android.content.Intent
import android.net.Uri
import androidx.activity.result.ActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.lifecycleScope
import com.armonia.app.data.repository.AuthSnapshot
import com.armonia.app.homelab.ManualInboxFailure
import com.armonia.app.homelab.checkedInbox
import com.armonia.app.homelab.manualUploadAccountMatches
import com.armonia.app.homelab.pickedMp3Body
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.ActivityCallback
import com.getcapacitor.annotation.CapacitorPlugin
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout

@CapacitorPlugin(name = "ArmoniaImport")
class ImportPlugin : Plugin() {
    private val host get() = activity as LibraryActivity
    private var pickerAccount: AuthSnapshot? = null

    @PluginMethod fun openBulkImport(call: PluginCall) {
        runCatching {
            val address = host.auth().serverUrl.trimEnd('/') + "/?abrir=importar-todo"
            host.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(address)))
        }.onSuccess { call.resolve() }.onFailure { call.reject("No se pudo abrir la importacion en el navegador.") }
    }

    @PluginMethod fun pickCover(call: PluginCall) = pick(call, true)
    @PluginMethod fun pickManualAudio(call: PluginCall) = pick(call, false)

    private fun pick(call: PluginCall, cover: Boolean) {
        host.runOnUiThread {
            if (pickerAccount != null) {
                call.reject("Ya hay un selector abierto.")
                return@runOnUiThread
            }
            runCatching {
                require(!call.getString("id").isNullOrBlank())
                if (cover) require(call.getString("kind") in setOf("local", "mixed"))
                else require(call.getInt("revision") != null)
                pickerAccount = host.auth()
                val types = if (cover) arrayOf("image/jpeg", "image/png", "image/webp") else arrayOf("audio/mpeg", "audio/mp3")
                val intent = ActivityResultContracts.OpenDocument().createIntent(host, types)
                startActivityForResult(call, intent, "picked")
            }.onFailure { pickerAccount = null; call.reject("No se pudo abrir el selector de archivos.") }
        }
    }

    @ActivityCallback private fun picked(call: PluginCall?, result: ActivityResult) {
        val account = pickerAccount
        pickerAccount = null
        if (call == null) return
        val uri = result.data?.data
        if (result.resultCode != Activity.RESULT_OK || uri == null) {
            call.resolve(JSObject().put("cancelled", true))
            return
        }
        host.lifecycleScope.launch {
            try {
                requireNotNull(account)
                val authorized = { manualUploadAccountMatches(account, host.prefs.cachedAuth) }
                check(authorized())
                val id = requireNotNull(call.getString("id"))
                if (call.methodName == "pickCover") {
                    val body = com.armonia.app.homelab.playlistCoverBody { host.contentResolver.openInputStream(uri) }
                    check(authorized())
                    val response = host.musicApi.uploadCover(requireNotNull(call.getString("kind")), id, account.userId, body, account)
                    check(response.isSuccessful && authorized())
                    call.resolve(JSObject().put("cancelled", false))
                    return@launch
                }
                val revision = requireNotNull(call.getInt("revision"))
                pickedMp3Body(host.contentResolver, uri, authorized).use { body ->
                    withTimeout(330_000) { host.musicApi.uploadManualInbox(id, revision, body, account).checkedInbox() }
                }
                check(authorized())
                call.resolve(JSObject().put("cancelled", false))
            } catch (e: Exception) {
                if (call.methodName == "pickCover") call.reject("No se pudo guardar la portada. Elige una imagen de hasta 8 MiB.")
                else call.reject((e as? ManualInboxFailure)?.userMessage ?: "No se pudo guardar el MP3. Actualiza la bandeja antes de reintentar.")
            }
        }
    }
}
