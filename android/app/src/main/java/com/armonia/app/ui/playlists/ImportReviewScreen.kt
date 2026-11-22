package com.armonia.app.ui.playlists

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import coil.compose.AsyncImage
import com.armonia.app.data.api.Playlist
import com.armonia.app.data.repository.LibraryRepository
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.homelab.*
import com.armonia.app.playback.MusicPlayer
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import javax.inject.Inject

@HiltViewModel
class ImportReviewViewModel @Inject constructor(
    private val api:MusicApi, private val prefs:PreferencesRepository,
    private val library:LibraryRepository, val player:MusicPlayer,
):ViewModel(){
    private val owner=prefs.cachedUserId
    /** The web flow for importing every Spotify playlist; null without a usable server address. */
    val importAllUrl:String?=prefs.cachedAuth.serverUrl.trim().trimEnd('/').takeIf{it.isNotBlank()}
        ?.let{(if(it.contains("://"))it else "http://$it")+"/?abrir=importar-todo"}
    var history by mutableStateOf<List<ImportSummary>>(emptyList());private set
    var playlists by mutableStateOf<List<Playlist>>(emptyList());private set
    var job by mutableStateOf<ImportJob?>(null);private set
    var busy by mutableStateOf(false);private set
    var error by mutableStateOf<String?>(null);private set
    var notice by mutableStateOf<String?>(null);private set
    var decisionFailures by mutableStateOf<Map<Int,ImportDecisionFailure>>(emptyMap());private set
    var focusRequest by mutableStateOf<Pair<Long,Int>?>(null);private set
    private var polling:Job?=null
    private var generation=0L
    private var selectedId:String?=null
    private var focusSerial=0L
    init{act{
        val loadedHistory=api.imports().checked().imports
        val loadedPlaylists=library.getPlaylists().getOrNull()?.playlists?.playlist.orEmpty()
        check(owner==prefs.cachedUserId)
        history=loadedHistory;playlists=loadedPlaylists
        importHistorySections(history).pending.firstOrNull()?.let{watch(it.importId)}
    }}
    private fun act(work:suspend()->Unit){if(busy)return;busy=true;error=null;viewModelScope.launch{
        try{check(owner==prefs.cachedUserId);work()}catch(e:CancellationException){throw e}
        catch(e:Exception){error=e.message}finally{busy=false}}}
    private fun stopPolling():Long {generation++;polling?.cancel();polling=null;return generation}
    private fun applySnapshot(result:ImportJob,epoch:Long):Boolean {
        if(owner!=prefs.cachedUserId)return false
        val currentRevision=job?.takeIf{it.importId==result.importId}?.revision
        if(!acceptsImportSnapshot(epoch,generation,selectedId,result.importId,currentRevision,result.revision))return false
        job=result;history=updateImportSummary(history,result);return true
    }
    fun watch(id:String){
        val epoch=stopPolling()
        if(selectedId!=id){job=null;decisionFailures=emptyMap();notice=null;focusRequest=null}
        selectedId=id
        polling=viewModelScope.launch{
            try{do{
                check(owner==prefs.cachedUserId)
                val result=api.importJob(id).checked()
                if(!applySnapshot(result,epoch))break
                if(result.status!="running")break
                delay(2000)
            }while(isActive)}
            catch(e:CancellationException){throw e}
            catch(e:Exception){if(epoch==generation&&owner==prefs.cachedUserId)error="No se pudo actualizar el progreso. Pulsa Actualizar para reintentar."}
        }
    }
    fun start(url:String,target:String?)=act{
        val result=api.startImport(owner,ImportStart(url,target)).checked()
        check(owner==prefs.cachedUserId)
        history=api.imports().checked().imports
        check(owner==prefs.cachedUserId);watch(result.importId)
    }
    fun decide(action:String,index:Int?=null,sourceId:String?=null,query:String?=null)=act{
        val current=job?:return@act
        if(current.hasPendingWork==false)return@act
        val item=index?.let{current.items.getOrNull(it)}
        if(index!=null&&(item==null||!canDecideImportItem(current,item)))return@act
        if(action=="confirm"||action=="skip")player.stopAudition()
        val before=orderedImportReview(current,decisionFailures).map{it.index}
        val epoch=stopPolling();notice=null
        try{
            val next=api.importDecision(current.importId,owner,ImportDecision(
                current.revision,action,index,sourceId,query,
                itemRevision=if(current.acceptingDecisions!=null&&item!=null)item.choiceRevision?:0 else null,
            )).checked()
            if(applySnapshot(next,epoch)&&index!=null){
                decisionFailures=decisionFailures-index
                if(action=="confirm"||action=="skip"){
                    notice=if(action=="confirm") "Elección guardada. El audio se procesa en segundo plano; puedes seguir con la siguiente canción."
                        else if(next.manualInboxAvailable==true&&next.items.getOrNull(index)?.manualPending==true) "Guardada en Pendientes de añadir. Puedes aportar un MP3 propio después desde Biblioteca."
                        else "Canción omitida. Puedes continuar revisando las demás."
                    nextImportReviewIndex(before,orderedImportReview(next,decisionFailures).map{it.index},index)?.let{
                        focusRequest=(++focusSerial) to it
                    }
                }
            }
        }catch(e:CancellationException){throw e}
        catch(e:Exception){
            if(epoch==generation&&owner==prefs.cachedUserId){
                val message="No se ha podido confirmar el resultado. Comprueba el progreso antes de reintentar."
                error=message
                if(index!=null){
                    val order=maxOf(current.items.maxOfOrNull{it.reviewOrder?:0}?:0,decisionFailures.values.maxOfOrNull{it.order}?:0)+1
                    decisionFailures=decisionFailures+(index to ImportDecisionFailure(order,message))
                }
            }
        }finally{if(epoch==generation&&owner==prefs.cachedUserId)watch(current.importId)}
    }
    fun pause()=act{job?.takeUnless{it.hasPendingWork==false}?.let{
        val epoch=stopPolling()
        try{applySnapshot(api.pauseImport(it.importId,owner).checked(),epoch)}
        finally{if(epoch==generation&&owner==prefs.cachedUserId)watch(it.importId)}
    }}
}

private fun clock(seconds: Double?): String =
    seconds?.toInt()?.takeIf { it > 0 }?.let { "%d:%02d".format(it / 60, it % 60) } ?: "duración desconocida"

/** One block of the screen. Blocks have keys so a row can be scrolled to without counting headers by hand. */
private class Block(val key: String, val content: @Composable () -> Unit)

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ImportReviewScreen(onBack:()->Unit,onInbox:()->Unit={},vm:ImportReviewViewModel=hiltViewModel()){
    var url by rememberSaveable{mutableStateOf("")}
    var target by rememberSaveable{mutableStateOf<String?>(null)}
    var showCompleted by rememberSaveable{mutableStateOf(false)}
    var showDetails by rememberSaveable{mutableStateOf(false)}
    var newOpen by rememberSaveable{mutableStateOf<Boolean?>(null)}
    val sections=importHistorySections(vm.history)
    val listState=rememberLazyListState()
    val previewing by vm.player.auditionId.collectAsState()
    DisposableEffect(Unit){onDispose{vm.player.stopAudition()}}
    val uriHandler=androidx.compose.ui.platform.LocalUriHandler.current
    val muted=MaterialTheme.colorScheme.onSurface.copy(alpha=.65f)
    val job=vm.job
    val review=job?.let{orderedImportReview(it,vm.decisionFailures)}.orEmpty()

    val blocks=buildList{
        // With an import waiting, that import is what the screen is for: the form folds away.
        val formOpen=newOpen?:(sections.pending.isEmpty()&&job==null)
        if(!formOpen)add(Block("new-folded"){OutlinedButton(onClick={newOpen=true},modifier=Modifier.fillMaxWidth()){
            Icon(Icons.Default.ExpandMore,null);Spacer(Modifier.width(6.dp));Text("Nueva importación")}})
        else add(Block("new"){NewImportCard(url,{url=it},target,{target=it},vm.playlists,
            canStart=url.isNotBlank()&&!vm.busy&&job?.status!="running",onStart={vm.start(url,target);newOpen=null},
            importAll=vm.importAllUrl?.let{address->{runCatching{uriHandler.openUri(address)};Unit}})})
        add(Block("pending-title"){SectionTitle("Importaciones pendientes",sections.pending.size.takeIf{it>0})})
        if(sections.pending.isEmpty())add(Block("pending-empty"){Text(
            if(vm.busy)"Consultando importaciones…"
            else if(vm.error!=null)"No se pudo comprobar si hay importaciones pendientes."
            else "No tienes importaciones pendientes.",color=muted,style=MaterialTheme.typography.bodyMedium)})
        sections.pending.forEach{h->add(Block("pending:${h.importId}"){
            ImportSummaryRow(h.name,songCount(h.total),selected=job?.importId==h.importId,enabled=!vm.busy){vm.watch(h.importId)}})}
        if(sections.completed.isNotEmpty())add(Block("history-toggle"){
            TextButton(onClick={showCompleted=!showCompleted},contentPadding=PaddingValues(horizontal=4.dp)){
                Icon(if(showCompleted)Icons.Default.ExpandLess else Icons.Default.ExpandMore,null)
                Spacer(Modifier.width(6.dp))
                Text(if(showCompleted)"Ocultar historial (${sections.completed.size})" else "Ver historial (${sections.completed.size})")}})
        if(showCompleted)sections.completed.forEach{h->add(Block("completed:${h.importId}"){
            ImportSummaryRow(h.name,"${songCount(h.total)} · Terminada",selected=job?.importId==h.importId,enabled=!vm.busy){vm.watch(h.importId)}})}
        vm.error?.let{message->add(Block("error"){Text(message,color=MaterialTheme.colorScheme.error,style=MaterialTheme.typography.bodyMedium)})}
        if(job!=null){
            add(Block("job"){JobCard(job,vm,showDetails,{showDetails=!showDetails},onInbox)})
            if(review.isNotEmpty())add(Block("review-title"){SectionTitle("Canciones que necesitan tu decisión",review.size)})
            review.forEach{entry->add(Block("item:${job.importId}:${entry.index}"){
                ReviewCard(job,entry.index,entry.value,vm,previewing)})}
        }
    }
    LaunchedEffect(vm.focusRequest){
        val current=vm.job?:return@LaunchedEffect
        val targetIndex=vm.focusRequest?.second?:return@LaunchedEffect
        val row=blocks.indexOfFirst{it.key=="item:${current.importId}:$targetIndex"}
        if(row>=0)listState.animateScrollToItem(row)
    }
    Scaffold(contentWindowInsets=WindowInsets(0),topBar={TopAppBar(
        title={Text("Importar playlist",style=MaterialTheme.typography.headlineMedium)},
        navigationIcon={IconButton(onClick=onBack){Icon(Icons.AutoMirrored.Filled.ArrowBack,"Volver; la importación sigue en segundo plano")}},
        colors=TopAppBarDefaults.topAppBarColors(containerColor=MaterialTheme.colorScheme.background))}){padding->
        LazyColumn(Modifier.padding(padding).fillMaxSize().imePadding(),state=listState,
            contentPadding=PaddingValues(start=16.dp,end=16.dp,top=4.dp,bottom=24.dp),verticalArrangement=Arrangement.spacedBy(10.dp)){
            items(blocks,key={it.key}){it.content()}
        }
    }
}

@Composable
private fun SectionTitle(text:String,count:Int?=null){
    Row(Modifier.padding(top=6.dp),verticalAlignment=Alignment.CenterVertically){
        Text(text,style=MaterialTheme.typography.titleMedium)
        if(count!=null){Spacer(Modifier.width(8.dp))
            Text("$count",style=MaterialTheme.typography.labelMedium,color=MaterialTheme.colorScheme.primary,
                modifier=Modifier.background(MaterialTheme.colorScheme.primary.copy(alpha=.14f),CircleShape).padding(horizontal=8.dp,vertical=2.dp))}
    }
}

@Composable
private fun cardColors()=CardDefaults.cardColors(containerColor=MaterialTheme.colorScheme.surface)

/** Source, destination and the action, in that order; "Importar todo" is the secondary way in. */
@Composable
private fun NewImportCard(url:String,onUrl:(String)->Unit,target:String?,onTarget:(String?)->Unit,playlists:List<Playlist>,
                          canStart:Boolean,onStart:()->Unit,importAll:(()->Unit)?){
    var choosing by remember{mutableStateOf(false)}
    val muted=MaterialTheme.colorScheme.onSurface.copy(alpha=.65f)
    Card(Modifier.fillMaxWidth(),colors=cardColors(),shape=RoundedCornerShape(14.dp)){
        Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(10.dp)){
            Text("Nueva importación",style=MaterialTheme.typography.titleMedium)
            OutlinedTextField(value=url,onValueChange=onUrl,label={Text("Enlace de la playlist de Spotify")},
                placeholder={Text("https://open.spotify.com/playlist/…")},singleLine=true,
                keyboardOptions=KeyboardOptions(imeAction=ImeAction.Go),keyboardActions=KeyboardActions(onGo={if(canStart)onStart()}),
                supportingText={Text("Tiene que ser pública. El enlace público puede mostrar solo las primeras 100 canciones.")},
                modifier=Modifier.fillMaxWidth())
            Box{
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(MaterialTheme.colorScheme.surfaceContainerHighest)
                    .clickable(role=Role.DropdownList){choosing=true}.padding(horizontal=12.dp,vertical=10.dp),
                    verticalAlignment=Alignment.CenterVertically){
                    Column(Modifier.weight(1f)){
                        Text("Destino",style=MaterialTheme.typography.labelMedium,color=muted)
                        Text(playlists.firstOrNull{it.id==target}?.let{"Recuperar en «${it.name}»"}?:"Crear una playlist nueva",
                            style=MaterialTheme.typography.bodyLarge,maxLines=1,overflow=TextOverflow.Ellipsis)
                    }
                    Icon(Icons.Default.ArrowDropDown,null)
                }
                DropdownMenu(expanded=choosing,onDismissRequest={choosing=false}){
                    DropdownMenuItem(text={Text("Crear una playlist nueva")},onClick={onTarget(null);choosing=false})
                    playlists.forEach{p->DropdownMenuItem(text={Text("Recuperar en «${p.name}»",maxLines=1,overflow=TextOverflow.Ellipsis)},
                        onClick={onTarget(p.id);choosing=false})}
                }
            }
            Button(onClick=onStart,enabled=canStart,modifier=Modifier.fillMaxWidth()){Text(if(target==null)"Importar" else "Recuperar en esta playlist")}
            if(importAll!=null){
                HorizontalDivider(color=MaterialTheme.colorScheme.onSurface.copy(alpha=.08f))
                Text("¿Quieres traer todas tus playlists de una vez?",style=MaterialTheme.typography.bodyMedium)
                OutlinedButton(onClick=importAll,modifier=Modifier.fillMaxWidth()){Text("Importar todo Spotify")}
                Text("Se abre en el navegador: inicia sesión en Armonía y elige el archivo de Exportify o conecta con Spotify. El progreso aparece después aquí, en Importaciones pendientes.",
                    style=MaterialTheme.typography.bodySmall,color=muted)
            }
        }
    }
}

@Composable
private fun ImportSummaryRow(name:String,detail:String,selected:Boolean,enabled:Boolean,onClick:()->Unit){
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
        .background(if(selected)MaterialTheme.colorScheme.primary.copy(alpha=.14f) else MaterialTheme.colorScheme.surface)
        .clickable(enabled=enabled,onClick=onClick).padding(horizontal=12.dp,vertical=10.dp),verticalAlignment=Alignment.CenterVertically){
        Box(Modifier.size(40.dp).clip(RoundedCornerShape(8.dp)).background(MaterialTheme.colorScheme.surfaceContainerHighest),contentAlignment=Alignment.Center){
            Icon(Icons.Default.MusicNote,null,tint=MaterialTheme.colorScheme.primary)}
        Column(Modifier.weight(1f).padding(horizontal=12.dp)){
            Text(name,style=MaterialTheme.typography.titleSmall,maxLines=1,overflow=TextOverflow.Ellipsis)
            Text(if(selected)"$detail · Abierta abajo" else detail,style=MaterialTheme.typography.bodySmall,
                color=MaterialTheme.colorScheme.onSurface.copy(alpha=.65f))
        }
        Icon(Icons.Default.ChevronRight,null,tint=MaterialTheme.colorScheme.onSurface.copy(alpha=.4f))
    }
}

@Composable
private fun Count(n:Int,label:String,color:Color=MaterialTheme.colorScheme.onSurface){
    if(n>0)Text("$n $label",style=MaterialTheme.typography.labelLarge,color=color,
        modifier=Modifier.background(color.copy(alpha=.12f),RoundedCornerShape(50)).padding(horizontal=10.dp,vertical=4.dp))
}

/** The open import: one progress line and counts first; the fine print behind "Detalles". */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun JobCard(job:ImportJob,vm:ImportReviewViewModel,showDetails:Boolean,onDetails:()->Unit,onInbox:()->Unit){
    val progress=ImportProgress.fromStates(job.items.map{it.state})
    val resumeLabel=importResumeLabel(job)
    val muted=MaterialTheme.colorScheme.onSurface.copy(alpha=.65f)
    val done=job.hasPendingWork==false
    Card(Modifier.fillMaxWidth(),colors=cardColors(),shape=RoundedCornerShape(14.dp)){
        Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(8.dp)){
            Row(verticalAlignment=Alignment.CenterVertically){
                Text(job.name,style=MaterialTheme.typography.titleLarge,maxLines=2,overflow=TextOverflow.Ellipsis,modifier=Modifier.weight(1f))
                Spacer(Modifier.width(8.dp))
                Text(if(done)"Terminada" else if(job.status=="running")"En curso" else "En pausa",
                    style=MaterialTheme.typography.labelMedium,
                    color=if(job.status=="running"&&!done)MaterialTheme.colorScheme.primary else muted)
            }
            LinearProgressIndicator(progress={if(job.total>0)progress.processed.toFloat()/job.total else 0f},
                modifier=Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)))
            Text("${progress.processed} de ${job.total} procesadas",style=MaterialTheme.typography.bodyMedium)
            if(done)Text("Importación terminada. Puedes volver a abrirla desde Historial.",style=MaterialTheme.typography.bodySmall,color=muted)
            vm.notice?.let{Text(it,style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.primary)}
            FlowRow(horizontalArrangement=Arrangement.spacedBy(6.dp),verticalArrangement=Arrangement.spacedBy(6.dp)){
                Count(progress.ready,"listas",MaterialTheme.colorScheme.primary)
                Count(progress.needsReview,"por revisar",Color(0xFFFFC46B))
                Count(progress.errors,"con error",MaterialTheme.colorScheme.error)
                Count(progress.inProgress,"en curso")
                Count(progress.queued,"por procesar")
                Count(progress.indexing,"esperando la biblioteca")
                Count(progress.skipped,"omitidas")
            }
            if(progress.indexing>0)Text(
                "${progress.indexing} descargadas y guardadas, esperando la biblioteca; no necesitan elegir otra versión. "+
                    (if(job.status=="running")"La biblioteca se comprueba al terminar las descargas."
                    else "Pulsa «$resumeLabel» para consultar de nuevo la biblioteca sin repetir estas descargas."),
                style=MaterialTheme.typography.bodySmall,color=muted)
            if(job.sourceInfo?.get("source_complete")?.asBoolean==false){
                val total=job.sourceInfo.get("source_total")?.takeIf{!it.isJsonNull}?.asInt
                Text(if(total!=null)"Importación parcial: la fuente tiene $total canciones y se han recuperado ${job.total}. Las que faltan no son canciones sin coincidencia."
                    else if(job.total<99)"Se han recuperado ${job.total} canciones. El enlace público no indica el total: si son las mismas que ves en la lista original, está completa."
                    else "Importación parcial: se han recuperado ${job.total} canciones. El enlace público solo muestra las primeras 100 y no indica el total.",
                    style=MaterialTheme.typography.bodySmall,color=Color(0xFFFFC46B))
                Text("Para completarla sin duplicados, usa «Completar con el archivo exportado» en la web.",style=MaterialTheme.typography.bodySmall,color=muted)
            }
            Row(horizontalArrangement=Arrangement.spacedBy(8.dp),verticalAlignment=Alignment.CenterVertically){
                if(!done){
                    if(job.status=="running")FilledTonalButton(onClick={vm.pause()},enabled=!vm.busy){Text("Pausar")}
                    else if(canResumeImport(job))Button(onClick={vm.decide("resume")},enabled=!vm.busy){Text(resumeLabel)}
                }
                OutlinedButton(onClick={vm.watch(job.importId)},enabled=!vm.busy){Text("Actualizar")}
            }
            // Secondary actions stay one tap away without competing with the main one.
            FlowRow(horizontalArrangement=Arrangement.spacedBy(4.dp)){
                if(!done&&job.status!="running")TextButton(onClick={vm.decide("refresh_source")},enabled=!vm.busy,
                    contentPadding=PaddingValues(horizontal=8.dp)){Text("Recuperar restantes")}
                if(job.manualInboxAvailable==true)TextButton(onClick=onInbox,contentPadding=PaddingValues(horizontal=8.dp)){Text("Pendientes de añadir")}
                TextButton(onClick=onDetails,contentPadding=PaddingValues(horizontal=8.dp)){
                    Icon(if(showDetails)Icons.Default.ExpandLess else Icons.Default.ExpandMore,null);Spacer(Modifier.width(4.dp));Text("Detalles")}
            }
            if(showDetails){
                Text("${job.downloaded} descargadas ahora · ${job.existing} ya estaban en tu biblioteca",style=MaterialTheme.typography.bodySmall,color=muted)
                if(progress.unavailable>0)Text("${progress.unavailable} posiciones sin metadatos en la fuente; no son rechazos de coincidencia.",style=MaterialTheme.typography.bodySmall,color=muted)
                job.error?.let{Text("Último error: $it",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.error)}
            }
        }
    }
}

/** One song waiting for a decision: what it is, why it stopped, candidates to listen to and choose. */
@Composable
private fun ReviewCard(job:ImportJob,index:Int,item:ImportItem,vm:ImportReviewViewModel,previewing:String?){
    val canDecide=!vm.busy&&canDecideImportItem(job,item)
    var query by rememberSaveable(job.importId,index){mutableStateOf("")}
    val muted=MaterialTheme.colorScheme.onSurface.copy(alpha=.65f)
    Card(Modifier.fillMaxWidth(),colors=cardColors(),shape=RoundedCornerShape(14.dp)){Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(8.dp)){
        Text("${index+1}. ${importItemHeading(item.state,item.track.title)}",style=MaterialTheme.typography.titleMedium)
        Text("${item.track.artist} · ${clock(item.track.duration)}",style=MaterialTheme.typography.bodyMedium,color=muted)
        vm.decisionFailures[index]?.let{Text(it.message,color=MaterialTheme.colorScheme.error,style=MaterialTheme.typography.bodySmall)}
        if((item.reviewOrder?:0)>0)Text(importFailureReason(item.reason),color=MaterialTheme.colorScheme.error,style=MaterialTheme.typography.bodySmall)
        if(canSearchImportAlternatives(item.state)){
            if(item.state=="download_failed")item.selected?.let{Text("Elegida: ${it.artist} — ${it.title}. Puedes reintentar la descarga o buscar otra fuente.",style=MaterialTheme.typography.bodySmall)}
            if(item.state=="source_unavailable")Text("Faltan metadatos de esta posición. Puedes buscarla manualmente o completar la fuente con el archivo exportado desde la web.",style=MaterialTheme.typography.bodySmall)
            if(item.acoustic?.get("status")?.asString=="no_reference")Text("Sin referencia acústica autorizada; no se ha comparado audio.",style=MaterialTheme.typography.bodySmall,color=muted)
            if(item.comparisonReason=="multiple_compatible_sources")Text("Varias fuentes coinciden en los metadatos. No se ha confirmado cuál es la misma grabación; elige la que prefieras.",style=MaterialTheme.typography.bodySmall)
            item.candidates.forEach{c->
                val song=remember(c.track.sourceId){c.track.toSong()}
                val sounding=previewing==song.id
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(MaterialTheme.colorScheme.surfaceContainerHighest).padding(8.dp),
                    verticalAlignment=Alignment.CenterVertically){
                    Box(Modifier.size(52.dp).clip(RoundedCornerShape(8.dp)).background(MaterialTheme.colorScheme.surfaceContainerHigh)
                        .clickable(role=Role.Button){if(sounding)vm.player.stopAudition() else vm.player.audition(song)}
                        .semantics{contentDescription=if(sounding)"Parar la preescucha" else "Escuchar 10 segundos de ${c.track.title}"},
                        contentAlignment=Alignment.Center){
                        if(c.track.source=="youtube")AsyncImage(model="https://i.ytimg.com/vi/${c.track.sourceId}/mqdefault.jpg",contentDescription=null,
                            contentScale=ContentScale.Crop,modifier=Modifier.fillMaxSize())
                        Icon(if(sounding)Icons.Default.Stop else Icons.Default.PlayArrow,null,tint=Color.White,
                            modifier=Modifier.size(24.dp).background(Color.Black.copy(alpha=.5f),CircleShape))
                    }
                    Column(Modifier.weight(1f).padding(horizontal=10.dp)){
                        Text(c.track.title,style=MaterialTheme.typography.titleSmall,maxLines=2,overflow=TextOverflow.Ellipsis)
                        Text("${c.track.artist} · ${clock(c.track.duration)}",style=MaterialTheme.typography.bodySmall,color=muted,maxLines=1,overflow=TextOverflow.Ellipsis)
                        if(c.reasons.isNotEmpty())Text(c.reasons.joinToString(" · "){importCandidateReason(it)},style=MaterialTheme.typography.labelSmall,color=muted,maxLines=2,overflow=TextOverflow.Ellipsis)
                    }
                    FilledTonalButton(onClick={vm.decide("confirm",index,c.track.sourceId)},enabled=canDecide,
                        contentPadding=PaddingValues(horizontal=14.dp)){Text("Elegir")}
                }
            }
            if(item.candidates.isNotEmpty())Text("Toca una miniatura para escuchar 10 segundos (del centro de la canción si se conoce su duración). Tu reproducción queda en pausa y vuelve al parar.",
                style=MaterialTheme.typography.bodySmall,color=muted)
            if(previewing!=null)TextButton(onClick={vm.player.stopAudition()},contentPadding=PaddingValues(0.dp)){Text("Volver a mi reproducción en pausa")}
            OutlinedTextField(value=query,onValueChange={query=it},placeholder={Text("Buscar otra opción")},singleLine=true,
                keyboardOptions=KeyboardOptions(imeAction=ImeAction.Search),
                keyboardActions=KeyboardActions(onSearch={if(query.isNotBlank()&&canDecide)vm.decide("search",index,query=query)}),
                trailingIcon={IconButton(onClick={vm.decide("search",index,query=query)},enabled=query.isNotBlank()&&canDecide){
                    Icon(Icons.Default.Search,"Buscar otra opción para ${item.track.title}")}},
                shape=RoundedCornerShape(12.dp),modifier=Modifier.fillMaxWidth())
            Row(horizontalArrangement=Arrangement.spacedBy(8.dp)){
                TextButton(onClick={vm.decide("skip",index)},enabled=canDecide){Text("Ninguna coincide")}
                TextButton(onClick={vm.decide("retry",index)},enabled=canDecide){Text("Reintentar")}
            }
        }else if(item.state=="skipped"||item.state=="indexing"){
            item.selected?.let{Text("Elegida: ${it.artist} — ${it.title}",style=MaterialTheme.typography.bodySmall)}
            TextButton(onClick={vm.decide("retry",index)},enabled=canDecide){Text("Reintentar")}
        }else{
            Text("Pulsa «Continuar» para reanudar el procesamiento; todavía no hay una elección que revisar.",style=MaterialTheme.typography.bodySmall,color=muted)
        }
    }}
}
