package com.armonia.app.playback

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import javax.inject.Inject
import javax.inject.Singleton

/** Things the playback service did on its own and the listener should be told, in a sentence. */
@Singleton
class PlaybackNotices @Inject constructor() {
    private val _messages = MutableSharedFlow<String>(extraBufferCapacity = 4)
    val messages: SharedFlow<String> = _messages
    fun post(message: String) { _messages.tryEmit(message) }
}
