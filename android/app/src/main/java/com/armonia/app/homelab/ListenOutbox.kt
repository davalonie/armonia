package com.armonia.app.homelab

import android.content.Context
import android.util.AtomicFile
import com.google.gson.Gson
import com.armonia.app.data.repository.PreferencesRepository
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton


/** Private app storage, one file per server/native identity. No passwords/tokens. */
@Singleton
class ListenOutbox @Inject constructor(
    @ApplicationContext private val context:Context,
    private val api:MusicApi,
    private val prefs:PreferencesRepository,
    private val gson:Gson,
) {
    private val problem = MutableStateFlow<String?>(null)
    val persistenceProblem = problem.asStateFlow()
    private val queue = DurableListenQueue(::read, ::save)
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
    init {scope.launch {while(isActive){runCatching{flush()};delay(30_000)}}}
    private fun file(account:String)=AtomicFile(File(context.filesDir,"listens-$account.json"))
    private fun read(account:String):List<PendingListen> {
        val f=file(account)
        if(!f.baseFile.exists() && !File(f.baseFile.path+".bak").exists()) return emptyList()
        // Fail closed on corruption: never overwrite an unreadable queue.
        return try {
            gson.fromJson(f.readFully().toString(Charsets.UTF_8),Array<PendingListen>::class.java).toList()
        } catch(e:Exception) {
            problem.value="No se puede leer la cola de escuchas. El archivo se conserva para recuperarlo; no se sobrescribe."
            throw e
        }
    }
    private fun save(account:String,events:List<PendingListen>) {
        val f=file(account);val stream=f.startWrite()
        try {stream.write(gson.toJson(events).toByteArray());f.finishWrite(stream)}
        catch(e:Exception){f.failWrite(stream);throw e}
    }
    suspend fun enqueue(account:String,owner:String,event:PlayEvent) = withContext(Dispatchers.IO) {
        try {
            queue.enqueue(account,owner,event)
            problem.value=null
        } catch (e:CancellationException) { throw e }
        catch (e:Exception) {
            problem.value="No se ha podido guardar una escucha en este telefono. Comprueba el almacenamiento; la cola existente se conserva."
            throw e
        }
        // Delivery belongs to the application, not a service which can be stopped.
        scope.launch { runCatching { flush() } }
    }
    suspend fun flush() {
        val auth=prefs.cachedAuth
        if(auth.userId.isBlank() || auth.sessionId.isBlank()) return
        queue.flush(auth.namespace,auth.userId,{prefs.cachedAuth==auth}) { pending ->
            api.listen(auth.userId,pending.event).code()
        }
    }
}
