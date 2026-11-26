package com.armonia.app.web

import android.content.ComponentName
import android.media.browse.MediaBrowser as PlatformBrowser
import android.os.SystemClock
import androidx.media3.common.MediaItem
import androidx.media3.session.MediaBrowser
import androidx.media3.session.SessionToken
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.armonia.app.playback.PlaybackService
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeNotNull
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.Callable
import java.util.concurrent.CompletableFuture
import java.util.concurrent.FutureTask
import java.util.concurrent.TimeUnit

/** Exercises the service entry point used by car browsers without opening a phone activity. */
@RunWith(AndroidJUnit4::class)
class CarLibraryTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private fun <T> onMain(block: () -> T): T {
        val task = FutureTask(Callable(block))
        instrumentation.runOnMainSync(task)
        return task.get()
    }

    @Test fun browsePlaylistThroughPlatformService() {
        val playlist = InstrumentationRegistry.getArguments().getString("playlist")
        assumeNotNull(playlist)
        val context = instrumentation.targetContext
        val titles = CompletableFuture<List<String>>()
        lateinit var browser: PlatformBrowser
        val connection = object : PlatformBrowser.ConnectionCallback() {
            override fun onConnected() {
                browser.subscribe("playlists", object : PlatformBrowser.SubscriptionCallback() {
                    override fun onChildrenLoaded(parentId: String, children: List<PlatformBrowser.MediaItem>) {
                        titles.complete(children.map { it.description.title.toString() })
                    }
                    override fun onError(parentId: String) {
                        titles.completeExceptionally(IllegalStateException("Could not browse $parentId"))
                    }
                })
            }
            override fun onConnectionFailed() {
                titles.completeExceptionally(IllegalStateException("Could not connect to platform browser service"))
            }
        }
        onMain {
            browser = PlatformBrowser(context, ComponentName(context, PlaybackService::class.java), connection, null)
            browser.connect()
        }
        try {
            assertTrue(playlist in titles.get(20, TimeUnit.SECONDS))
        } finally {
            onMain { browser.disconnect() }
        }
    }

    @Test fun browseAndPlayFromCar() {
        val playlist = InstrumentationRegistry.getArguments().getString("playlist")
        assumeNotNull(playlist)
        val context = instrumentation.targetContext
        val token = SessionToken(context, ComponentName(context, PlaybackService::class.java))
        val browser = onMain { MediaBrowser.Builder(context, token).buildAsync() }.get(20, TimeUnit.SECONDS)
        try {
            val root = onMain { browser.getLibraryRoot(null) }.get(10, TimeUnit.SECONDS).value!!
            fun children(parent: String) =
                onMain { browser.getChildren(parent, 0, 100, null) }.get(20, TimeUnit.SECONDS).value!!
            assertTrue(children(root.mediaId).any { it.mediaId == "playlists" })
            val list = children("playlists").single { it.mediaMetadata.title.toString() == playlist }
            val tracks = children(list.mediaId)
            assertTrue(tracks.size >= 2)
            onMain {
                browser.setMediaItem(MediaItem.Builder().setMediaId(tracks.first().mediaId).build())
                browser.prepare()
                browser.play()
            }
            val until = SystemClock.elapsedRealtime() + 20_000
            while (!onMain { browser.isPlaying } && SystemClock.elapsedRealtime() < until) SystemClock.sleep(200)
            assertTrue(onMain { browser.isPlaying })
            assertEquals(tracks.size, onMain { browser.mediaItemCount })
            assertEquals(tracks.first().mediaMetadata.title.toString(), onMain { browser.mediaMetadata.title.toString() })
            val duration = onMain { browser.duration }
            assertTrue(duration in 30_000..120_000)
            SystemClock.sleep(duration / 2 + 4500)
            assertTrue(onMain { browser.currentPosition >= duration / 2 })
        } finally {
            onMain { browser.pause(); browser.release() }
        }
    }
}
