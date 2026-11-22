package com.armonia.app.playback

import android.os.Bundle
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.Timeline

/**
 * A song queued by hand carries a mark in its metadata (see HandPickedQueue): the player's own
 * queue says which songs those are, wherever it is read from (the service, the phone UI, a queue
 * restored after a preview or a restart). The mark is a token unique to that insertion, so
 * «Deshacer» removes exactly the entry it added and not another copy of the same song.
 */
private const val HAND_PICKED = "armonia.handPicked"

fun MediaItem.handPicked(token: String): MediaItem {
    val extras = Bundle(mediaMetadata.extras ?: Bundle()).apply { putString(HAND_PICKED, token) }
    return buildUpon().setMediaMetadata(mediaMetadata.buildUpon().setExtras(extras).build()).build()
}

fun MediaItem.handPickedToken(): String? = mediaMetadata.extras?.getString(HAND_PICKED)

/** «Añadir al final de la cola» marks its entry too, only for «Deshacer»: it is not queued next. */
private const val QUEUED_AT_END = "armonia.queuedAtEnd"

fun MediaItem.queuedAtEnd(token: String): MediaItem {
    val extras = Bundle(mediaMetadata.extras ?: Bundle()).apply { putString(QUEUED_AT_END, token) }
    return buildUpon().setMediaMetadata(mediaMetadata.buildUpon().setExtras(extras).build()).build()
}

/** The token of whichever insertion by hand put this entry in the queue. */
fun MediaItem.queuedToken(): String? = handPickedToken() ?: mediaMetadata.extras?.getString(QUEUED_AT_END)

fun Player.handPickedIndices(): Set<Int> =
    (0 until mediaItemCount).filterTo(HashSet()) { getMediaItemAt(it).handPickedToken() != null }

/** Queue indices in the order they play: the queue itself, or the shuffle order. */
fun Timeline.playOrder(shuffle: Boolean): List<Int> {
    val order = ArrayList<Int>(windowCount)
    if (isEmpty) return order
    var i = getFirstWindowIndex(shuffle)
    while (i != C.INDEX_UNSET && order.size < windowCount) {
        order.add(i)
        i = getNextWindowIndex(i, Player.REPEAT_MODE_OFF, shuffle)
    }
    return order
}
