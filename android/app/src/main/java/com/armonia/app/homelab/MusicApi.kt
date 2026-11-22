package com.armonia.app.homelab

import com.google.gson.JsonObject
import com.google.gson.annotations.SerializedName
import com.armonia.app.data.api.Song
import retrofit2.Response
import retrofit2.http.*

data class MusicTrack(
    val source: String,
    @SerializedName("source_id") val sourceId: String,
    val title: String,
    val artist: String,
    val album: String = "",
    val duration: Double? = null,
    @SerializedName("recording_mbid") val recordingMbid: String? = null,
    @SerializedName("artist_mbids") val artistMbids: List<String> = emptyList(),
    val isrc: String? = null,
) {
    fun toSong(): Song = Song(
        id=when(source){"youtube"->"preview|$sourceId";"authorized_http"->"external|$sourceId";else->sourceId},
        parent=null,title=title,album=album,artist=artist,track=null,year=null,genre=null,coverArt=null,
        duration=duration?.toInt()?:0,bitRate=null,contentType=null,suffix=null,size=null,albumId=null,
        artistId=null,type=null,created=null,starred=null,musicTrack=this,
    )
}
fun Song.asMusicTrack(): MusicTrack = musicTrack ?: MusicTrack(
    source=when {id.startsWith("preview|")->"youtube";id.startsWith("external|")->"authorized_http";else->"navidrome"},
    sourceId=id.substringAfter('|', id), title=title, artist=artist, album=album?:"", duration=duration.takeIf{it>0}?.toDouble(),
    recordingMbid=musicBrainzId?.takeIf{validMbid(it)},
    artistMbids=artists.orEmpty().mapNotNull{it.musicBrainzId?.takeIf{value->validMbid(value)}}.distinct().take(20),
    isrc=isrc?.firstOrNull{it.matches(Regex("[A-Z]{2}[A-Z0-9]{3}[0-9]{7}"))},
)
private fun validMbid(value:String)=value.matches(Regex("[a-fA-F0-9]{8}(-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}"))
data class MixedItem(val id: String, val track: MusicTrack)
data class MixedPlaylist(val id: String?=null, val name: String, val revision: Int=0, val items: List<MixedItem> = emptyList())
data class PlaylistBody(val name:String,val revision:Int,val items:List<MixedItem>)
data class MixedSummary(val id:String, val name:String, val revision:Int, @SerializedName("item_count") val itemCount:Int)
data class MixedLists(val playlists:List<MixedSummary>)
data class SourceList(val tracks:List<MusicTrack>)
data class DiscoverySeed(val name:String,val mbid:String?,val status:String?,val reason:String?) {
    fun explanation():String = when(reason) {
        "recording_metadata" -> "Identificado por los metadatos de tus grabaciones"
        "name_and_recording" -> "Nombre y canción contrastados en MusicBrainz"
        "multiple_artists" -> "Hay varios artistas con ese nombre"
        "conflicting_ids" -> "Identificadores contradictorios"
        "metadata_unavailable" -> "Proveedor de metadatos no disponible"
        "not_found" -> "Sin coincidencia de nombre en MusicBrainz"
        else -> "Falta evidencia para verificar la identidad"
    }
}
data class ArtistRecommendation(val name:String,val sourceArtist:String?,val provenance:String?,val seeds:List<DiscoverySeed>?)
data class DiscoverResult(val artists:List<ArtistRecommendation>,val version:Int?,val state:String?,val seeds:List<DiscoverySeed>?,val partial:Boolean?) {
    fun personalArtists() = if(version==1) artists.filter { it.provenance=="similar_to_identified_seed" && !it.seeds.isNullOrEmpty() } else emptyList()
}
data class MusicFlow(val id:String,val name:String,val autoDownload:Boolean)
data class FlowList(val flows:List<MusicFlow>)
data class Recording(val title:String,val artist:String,val album:String?=null,val duration:Double?=null,val isrc:String?=null)
data class FlowTracks(val tracks:List<Recording>)
data class Candidate(val track:MusicTrack,val score:Double,val reasons:List<String>)
data class MatchResult(val selected:MusicTrack?,val candidates:List<Candidate>)
data class AccountLink(val username:String,val password:String)
data class PlayEvent(val id:String,val track:MusicTrack,
    @SerializedName("started_at") val startedAt:Long,
    @SerializedName("listened_seconds") val listenedSeconds:Double)

data class PlaylistContext(val kind:String,val id:String)
data class RecentPlaylist(val kind:String,val id:String,val name:String,val coverArt:String?,val covers:List<CoverRef>?=null)
data class CoverRef(val source:String,@SerializedName("source_id") val sourceId:String,val cover:String?)
data class GeneratedItem(val id:String,val track:MusicTrack,val cover:String?)
data class GeneratedPlaylist(val key:String,val kind:String,val name:String,val description:String,val state:String,
    val error:String?,val updated:Long,val count:Int,val covers:List<CoverRef>?,val items:List<GeneratedItem>?)
data class WeeklyReport(val proposed:Int=0,val listed:Int=0)
data class HomeStatus(val updating:Boolean,val checked:Long?,val profile:String?,val error:String?,val weekly:WeeklyReport?=null)
data class HomePlaylists(val playlists:List<GeneratedPlaylist>,val status:HomeStatus)
data class HomeArtist(val name:String,val channelId:String,val thumbnail:String?,val similarTo:String?)
data class HomeArtists(val artists:List<HomeArtist>)
data class HomeRefresh(val status:HomeStatus)
data class PlaybackSettings(@SerializedName("continue_similar") val continueSimilar:Boolean=true)
data class SavingRequest(val ids:List<String>)
data class ContinueRequest(val artists:List<String>,val exclude:List<String>)
data class ContinueBatch(val enabled:Boolean=true,val items:List<GeneratedItem> = emptyList())
data class SavedCopy(val id:String,val name:String,val count:Int)
data class RecentPlaylists(val playlists:List<RecentPlaylist>)
data class ImportSummary(val importId:String,val name:String,val total:Int,
    val hasPendingWork:Boolean?=null,val legacySkipped:Int?=null)
data class ImportHistory(val imports:List<ImportSummary>)
data class ImportStart(val url:String,val playlistId:String?=null)
data class ImportItem(val track:Recording,val state:String,val candidates:List<Candidate>,val selected:MusicTrack?,val acoustic:JsonObject?,
    val choiceRevision:Int?=null,val reviewOrder:Long?=null,val reason:String?=null,
    @SerializedName("comparison_reason") val comparisonReason:String?=null,val manualPending:Boolean?=null)
data class ImportJob(val importId:String,val name:String,val status:String,val revision:Int,val total:Int,val current:Int,
    val downloaded:Int,val existing:Int,val failed:Int,val items:List<ImportItem>,val sourceInfo:JsonObject?,val unavailable:Int?,
    val acceptingDecisions:Boolean?=null,val manualInboxAvailable:Boolean?=null,
    val hasPendingWork:Boolean?=null,val legacySkipped:Int?=null,val error:String?=null)
data class ImportDecision(val revision:Int,val action:String,val index:Int?=null,
    @SerializedName("source_id") val sourceId:String?=null,val query:String?=null,val itemRevision:Int?=null)

data class NewRelease(val id: String, val title: String, val artist: String, val type: String,
    val date: String, val upcoming: Boolean, val hasCover: Boolean)
data class ReleaseCalendar(val preparing: Boolean, val items: List<NewRelease>)
data class ReleaseTracks(val items: List<GeneratedItem>, val preparing: Boolean)

interface MusicApi {
    @GET("/api/home/releases") suspend fun releases(): Response<ReleaseCalendar>
    @GET("/api/home/releases/{id}") suspend fun releaseTracks(@Path("id") id: String): Response<ReleaseTracks>
    @GET("/api/manual-inbox") suspend fun manualInbox(@Tag auth:com.armonia.app.data.repository.AuthSnapshot):Response<ManualInboxResult>
    @POST("/api/manual-inbox/{id}/upload") suspend fun uploadManualInbox(@Path("id") id:String,
        @Header("X-Item-Revision") revision:Int,@Body audio:okhttp3.RequestBody,
        @Tag auth:com.armonia.app.data.repository.AuthSnapshot):Response<ManualInboxItem>
    @POST("/api/manual-inbox/{id}/refresh") suspend fun refreshManualInbox(@Path("id") id:String,
        @Body body:ManualInboxRevision,@Tag auth:com.armonia.app.data.repository.AuthSnapshot):Response<ManualInboxItem>
    @HTTP(method="DELETE",path="/api/manual-inbox/{id}",hasBody=true) suspend fun removeManualInbox(@Path("id") id:String,
        @Body body:ManualInboxRevision,@Tag auth:com.armonia.app.data.repository.AuthSnapshot):Response<JsonObject>
    @GET("/api/recent-playlists") suspend fun recentPlaylists(@Query("kinds") kinds:String="generated"):Response<RecentPlaylists>
    @GET("/api/home/playlists") suspend fun homePlaylists():Response<HomePlaylists>
    @GET("/api/home/playlists/{key}") suspend fun homePlaylist(@Path("key") key:String):Response<GeneratedPlaylist>
    @GET("/api/home/artists") suspend fun homeArtists():Response<HomeArtists>
    @POST("/api/home/playlists/refresh") suspend fun refreshHome(@Header("X-Music-Owner") owner:String):Response<HomeRefresh>
    @POST("/api/home/weekly") suspend fun activateWeekly(@Header("X-Music-Owner") owner:String):Response<HomeRefresh>
    @POST("/api/home/playlists/{key}/save") suspend fun saveGenerated(@Path("key") key:String,@Header("X-Music-Owner") owner:String):Response<SavedCopy>
    @POST("/api/recent-playlists") suspend fun rememberPlaylist(@Header("X-Music-Owner") owner:String,@Body body:PlaylistContext):Response<JsonObject>
    @GET("/api/home/settings") suspend fun playbackSettings():Response<PlaybackSettings>
    @PUT("/api/home/settings") suspend fun savePlaybackSettings(@Header("X-Music-Owner") owner:String,@Body body:PlaybackSettings):Response<PlaybackSettings>
    @POST("/api/home/continue") suspend fun continueSimilar(@Header("X-Music-Owner") owner:String,@Body body:ContinueRequest):Response<ContinueBatch>
    @GET("/api/imports") suspend fun imports():Response<ImportHistory>
    @GET("/api/import/{id}") suspend fun importJob(@Path("id") id:String):Response<ImportJob>
    @POST("/api/import/spotify") suspend fun startImport(@Header("X-Music-Owner") owner:String,@Body body:ImportStart):Response<ImportSummary>
    @POST("/api/import/{id}/decision") suspend fun importDecision(@Path("id") id:String,@Header("X-Music-Owner") owner:String,@Body body:ImportDecision):Response<ImportJob>
    @POST("/api/import/{id}/cancel") suspend fun pauseImport(@Path("id") id:String,@Header("X-Music-Owner") owner:String):Response<ImportJob>
    @POST("/api/stream/preparar") suspend fun prepareSaving(@Body body:SavingRequest):Response<Unit>
    @POST("/api/preview/{id}/prepare") suspend fun prepare(@Path("id") id:String,@Header("X-Music-Owner") owner:String,
        @Tag auth:com.armonia.app.data.repository.AuthSnapshot?=null):Response<JsonObject>
    @GET("/api/sources") suspend fun sources(): Response<SourceList>
    @GET("/api/discover") suspend fun discover(): Response<DiscoverResult>
    @GET("/api/discover/flows") suspend fun flows(): Response<FlowList>
    @GET("/api/discover/flows/{id}") suspend fun flow(@Path("id") id:String): Response<FlowTracks>
    @POST("/api/discover/weekly") suspend fun weekly(@Header("X-Music-Owner") owner:String): Response<JsonObject>
    @POST("/api/discover/flows/{id}/refresh") suspend fun refreshFlow(@Path("id") id:String,@Header("X-Music-Owner") owner:String): Response<JsonObject>
    @GET("/api/discover/history") suspend fun history(): Response<JsonObject>
    @POST("/api/discover/match") suspend fun match(@Body track:Recording): Response<MatchResult>
    @GET("/api/integrations/aurral") suspend fun linkStatus(): Response<Map<String, Boolean>>
    @POST("/api/integrations/aurral") suspend fun link(@Header("X-Music-Owner") owner:String,@Body body:AccountLink): Response<JsonObject>
    @DELETE("/api/integrations/aurral") suspend fun unlink(@Header("X-Music-Owner") owner:String): Response<JsonObject>
    @GET("/api/mixed-playlists") suspend fun playlists(): Response<MixedLists>
    @GET("/api/mixed-playlists/{id}") suspend fun playlist(@Path("id") id:String): Response<MixedPlaylist>
    @POST("/api/mixed-playlists") suspend fun create(@Header("X-Music-Owner") owner:String,@Body body:PlaylistBody): Response<MixedPlaylist>
    @PUT("/api/mixed-playlists/{id}") suspend fun update(@Path("id") id:String,@Header("X-Music-Owner") owner:String,@Body body:PlaylistBody): Response<MixedPlaylist>
    @DELETE("/api/mixed-playlists/{id}") suspend fun delete(@Path("id") id:String,@Query("revision") revision:Int,@Header("X-Music-Owner") owner:String): Response<JsonObject>
    @POST("/api/mixed-playlists/{id}/export-navidrome") suspend fun export(@Path("id") id:String,@Header("X-Music-Owner") owner:String,@Body revision:Map<String,Int>): Response<JsonObject>
    @GET("/api/listening/summary") suspend fun summary(@Query("period") period: String): Response<ListeningSummary>
    @POST("/api/listening/events") suspend fun listen(@Header("X-Music-Owner") owner:String,@Body event:PlayEvent): Response<JsonObject>
    @GET("/api/listening/top/{kind}") suspend fun top(@Path("kind") kind:String,@Query("period") period:String="month"): Response<JsonObject>
    @GET("/api/listening/status") suspend fun delivery(): Response<JsonObject>
    @GET("/api/sources/{source}/{id}/capabilities") suspend fun capabilities(@Path("source") source:String,@Path("id") id:String): Response<Map<String,Boolean>>
    @POST("/api/sources/{id}/save") suspend fun saveSource(@Path("id") id:String,@Header("X-Music-Owner") owner:String): Response<JsonObject>
}
fun <T> Response<T>.checked(): T {
    if(!isSuccessful) throw IllegalStateException(when(code()) {
        401->"Sesión caducada";403->"Acción no autorizada";404->"Recurso no disponible";
        409->"Ha cambiado la cuenta o la playlist. Recarga antes de guardar.";
        424->"Vincula tu cuenta de recomendaciones";else->"Servicio no disponible (HTTP ${code()})"
    })
    return body() ?: throw IllegalStateException("Respuesta vacía")
}

data class ListenRank(val name: String, val seconds: Double, val count: Int, val track: MusicTrack)
data class ListenBucket(val date: String, val seconds: Double)
data class RecentListen(val at: Long, val track: MusicTrack)
data class ListeningSummary(val seconds: Double, val count: Int, val distinct: Int, val artists: List<ListenRank>,
    val songs: List<ListenRank>, val albums: List<ListenRank>, val recent: List<RecentListen>, val series: List<ListenBucket>)
