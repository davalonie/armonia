package com.armonia.app.playback

import android.os.SystemClock
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import com.google.gson.Gson
import com.armonia.app.data.repository.LibraryRepository
import com.armonia.app.data.repository.PreferencesRepository
import com.armonia.app.homelab.*
import kotlinx.coroutines.*
import java.util.UUID

/** Runs in the existing playback service, including background/Auto/offline. */
class Scrobbler(
    private val player:Player,
    private val repository:LibraryRepository,
    private val scope:CoroutineScope,
    private val prefs:PreferencesRepository,
    private val outbox:ListenOutbox,
) : Player.Listener {
    private var clock=ListeningClock()
    private var tracker=ScrobbleTracker()
    private var ticker:Job?=null
    private var track:MusicTrack?=null
    private var eventId=""
    private var account=""
    private var owner=""
    private var started=0L
    private data class MainListen(val clock:ListeningClock,val tracker:ScrobbleTracker,val track:MusicTrack?,
        val eventId:String,val account:String,val owner:String,val started:Long)
    private var mainListen:MainListen?=null
    fun attach(){player.addListener(this);onMediaItemTransition(player.currentMediaItem,0)}
    override fun onMediaItemTransition(mediaItem:MediaItem?,reason:Int) {
        val audition = mediaItem?.mediaMetadata?.extras?.getBoolean("audition",false) == true
        if (audition) {
            if (mainListen == null) mainListen = MainListen(clock,tracker,track,eventId,account,owner,started)
            clock = ListeningClock(); tracker = ScrobbleTracker(); track = null
            return
        }
        val id=mediaItem?.mediaId?.let{realTrackId(it)}
        val saved = mainListen
        mainListen = null
        if (saved != null && saved.track?.sourceId == id?.substringAfter('|',id) && saved.account == prefs.accountNamespace) {
            clock=saved.clock;tracker=saved.tracker;track=saved.track;eventId=saved.eventId
            account=saved.account;owner=saved.owner;started=saved.started
            clock.sample(player.currentPosition,SystemClock.elapsedRealtime(),false,true)
            return
        }
        clock=ListeningClock();tracker=ScrobbleTracker();eventId=UUID.randomUUID().toString();started=System.currentTimeMillis()/1000
        account=prefs.accountNamespace;owner=prefs.cachedUserId
        val md=mediaItem?.mediaMetadata
        track=if(id==null||md==null) null else {
            md.extras?.getString("musicTrack")?.let{runCatching{Gson().fromJson(it,MusicTrack::class.java)}.getOrNull()}
                ?: MusicTrack(when{ id.startsWith("preview|")->"youtube";id.startsWith("external|")->"authorized_http";else->"navidrome"},
                    id.substringAfter('|',id),md.title?.toString()?:"Unknown",md.artist?.toString()?:"Unknown",md.albumTitle?.toString()?:"")
        }
        tracker.onTrackStarted(id)
        if(id!=null && !isPreviewMediaId(id)) scope.launch{runCatching{repository.scrobble(id,false)}}
        sample()
    }
    override fun onPositionDiscontinuity(oldPosition:Player.PositionInfo,newPosition:Player.PositionInfo,reason:Int) {
        clock.sample(player.currentPosition,SystemClock.elapsedRealtime(),false,true)
    }
    override fun onIsPlayingChanged(isPlaying:Boolean) {
        ticker?.cancel()
        clock.sample(player.currentPosition,SystemClock.elapsedRealtime(),isPlaying)
        ticker=if(isPlaying) scope.launch{while(isActive){sample();delay(1_000)}} else null
    }
    private fun sample() {
        clock.sample(player.currentPosition,SystemClock.elapsedRealtime(),player.isPlaying)
        val duration=player.duration.coerceAtLeast(0L)
        val current=track ?: return
        if(tracker.onProgress(clock.heardMs,duration)==null) return
        val snapshot=PlayEvent(eventId,current.copy(duration=duration.takeIf{it>0}?.div(1000.0)),started,clock.heardMs/1000.0)
        val eventAccount=account;val eventOwner=owner
        scope.launch {
            // Never mix an old play into the account selected while delivery waits.
            runCatching{outbox.enqueue(eventAccount,eventOwner,snapshot)}
            if(current.source=="navidrome" && eventOwner==prefs.cachedUserId && eventAccount==prefs.accountNamespace)
                runCatching{repository.scrobble(current.sourceId,true)}
        }
    }
}
