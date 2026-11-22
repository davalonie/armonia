package com.armonia.app.ui.homelab

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.armonia.app.homelab.*
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.playback.MusicPlayer
import com.armonia.app.offline.OfflineManager
import com.armonia.app.offline.OfflineCollection
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import java.util.UUID
import javax.inject.Inject

@HiltViewModel
class HomelabViewModel @Inject constructor(
    private val api:MusicApi, private val prefs:PreferencesRepository,
    private val library:com.armonia.app.data.repository.LibraryRepository,
    val player:MusicPlayer, private val offline:OfflineManager, val listenOutbox:ListenOutbox,
):ViewModel(){
    val offlineProblem = offline.persistenceProblem
    private val owner = prefs.cachedUserId
    var recentPlaylists by mutableStateOf<List<RecentPlaylist>>(emptyList());private set
    var sources by mutableStateOf<List<MusicTrack>>(emptyList());private set
    var artists by mutableStateOf<List<ArtistRecommendation>>(emptyList());private set
    var discoveryState by mutableStateOf("insufficient_profile");private set
    var discoverySeeds by mutableStateOf<List<DiscoverySeed>>(emptyList());private set
    var flows by mutableStateOf<List<MusicFlow>>(emptyList());private set
    var recommendations by mutableStateOf<List<Recording>>(emptyList());private set
    var candidates by mutableStateOf<List<Candidate>>(emptyList());private set
    var reviewOriginal by mutableStateOf<Recording?>(null);private set
    var lists by mutableStateOf<List<MixedSummary>>(emptyList());private set
    var selected by mutableStateOf<MixedPlaylist?>(null)
    var stats by mutableStateOf<List<Pair<String,Int>>>(emptyList());private set
    var recent by mutableStateOf<List<Recording>>(emptyList());private set
    var error by mutableStateOf<String?>(null);private set
    var busy by mutableStateOf(false);private set
    fun act(block:suspend()->Unit){if(busy)return;busy=true;error=null;viewModelScope.launch{try{check(owner==prefs.cachedUserId){"La cuenta ha cambiado; vuelve a abrir esta pantalla"};block()}catch(e:Exception){error=e.message?:"Servicio no disponible"}finally{busy=false}}}

    fun load()=act{
        runCatching{api.recentPlaylists().checked()}.onSuccess{recentPlaylists=it.playlists}
        sources=api.sources().checked().tracks
        lists=api.playlists().checked().playlists
        runCatching{api.discover().checked()}.onSuccess{artists=it.personalArtists();discoveryState=it.state?:"insufficient_profile";discoverySeeds=it.seeds?:emptyList()}.onFailure{error=it.message}
        runCatching{api.flows().checked()}.onSuccess{flows=it.flows}
        runCatching{api.history().checked()}.onSuccess{data->
            recent=data.getAsJsonArray("snapshots")?.flatMap{s->s.asJsonObject.getAsJsonArray("tracks")?.map{
                val t=it.asJsonObject;Recording(t["title"].asString,t["artist"].asString)
            }?:emptyList()}?:emptyList()
        }
    }
    fun link(username:String,password:String)=act{api.link(owner,AccountLink(username,password)).checked();val result=api.discover().checked();artists=result.personalArtists();discoveryState=result.state?:"insufficient_profile";discoverySeeds=result.seeds?:emptyList();flows=api.flows().checked().flows}
    fun weekly()=act{api.weekly(owner).checked();flows=api.flows().checked().flows}
    fun flow(id:String)=act{recommendations=api.flow(id).checked().tracks}
    fun refreshFlow(id:String)=act{api.refreshFlow(id,owner).checked();error="Generación solicitada. Actualiza la lista en unos momentos."}
    fun match(track:Recording){val epoch=player.routeGuard.explicitPlay();act{val r=api.match(track).checked();candidates=if(r.selected==null)r.candidates else emptyList();reviewOriginal=if(r.selected==null)track else null;r.selected?.let{player.playQueue(listOf(it.toSong()),requestEpoch=epoch)}}}
    fun saveSource(track:MusicTrack)=act{check(api.capabilities(track.source,track.sourceId).checked()["persist"]==true){"Esta fuente no permite guardado permanente"};api.saveSource(track.sourceId,owner).checked();error="Guardada en biblioteca; el escaneo puede tardar"}
    fun playRecent(p:RecentPlaylist){val epoch=player.routeGuard.explicitPlay();act{
        val songs=if(p.kind=="mixed")api.playlist(p.id).checked().items.map{it.track.toSong()}
            else library.getPlaylist(p.id).getOrThrow().playlist?.entry.orEmpty()
        player.playQueue(songs,requestEpoch=epoch,playlistId=p.id,playlistKind=p.kind)
    }}
    fun play(track:MusicTrack)=player.play(track.toSong())
    fun playList(){selected?.let{p->val songs=p.items.map{it.track.toSong()};player.playQueue(songs, player.collectionStart(songs),playlistId=p.id,playlistKind="mixed")}}
    private suspend fun save(p:MixedPlaylist){val body=PlaylistBody(p.name,p.revision,p.items);selected=(if(p.id==null)api.create(owner,body)else api.update(p.id,owner,body)).checked();lists=api.playlists().checked().playlists}
    fun select(id:String)=act{selected=api.playlist(id).checked()}
    fun create(name:String)=act{save(MixedPlaylist(name=name))}
    fun rename(name:String)=act{selected?.let{save(it.copy(name=name))}}
    fun addCurrent()=act{val p=selected?:return@act;val song=player.currentSong.value?:return@act;save(p.copy(items=p.items+MixedItem(UUID.randomUUID().toString(),song.asMusicTrack())))}
    fun remove(index:Int)=act{selected?.let{p->save(p.copy(items=p.items.filterIndexed{i,_->i!=index}))}}
    fun move(index:Int,delta:Int)=act{selected?.let{p->val items=p.items.toMutableList();if(index+delta in items.indices){val item=items.removeAt(index);items.add(index+delta,item);save(p.copy(items=items))}}}
    fun delete()=act{selected?.let{api.delete(it.id!!,it.revision,owner).checked()};selected=null;lists=api.playlists().checked().playlists}
    fun export()=act{selected?.let{val r=api.export(it.id!!,owner,mapOf("revision" to it.revision)).checked();error="Copia en Navidrome: ${r["exported"]} canciones; ${r["omitted"]} externas omitidas"}}
    fun pin()=act{selected?.let{p->
        for(item in p.items) if(item.track.source!="navidrome") check(api.capabilities(item.track.source,item.track.sourceId).checked()["offline"]==true){"Una canción no permite descarga offline"}
        // Reuse Media3 DownloadManager and the existing offline catalogue.
        offline.pin(OfflineCollection(key="mixed:${p.id}",title=p.name,subtitle="Playlist mixta",coverArt=null,songs=p.items.map{it.track.toSong()},pinnedAt=System.currentTimeMillis()))
    }}
    fun top(kind:String="artists")=act{val data=api.top(kind).checked();stats=data.getAsJsonArray("items")?.map{r->val item=r.asJsonObject.getAsJsonObject("item");(item["name"]?.asString?:item["title"]?.asString?:"Sin título") to (item["listen_count"]?.asInt?:0)}?:emptyList()}
}
