package com.armonia.app.playback

import javax.inject.Inject
import javax.inject.Singleton

/** A route loss invalidates work requested before it; reconnecting never grants playback. */
@Singleton
class RoutePauseGuard @Inject constructor() {
    @Volatile var epoch: Long = 0; private set
    @Volatile var blocked: Boolean = false; private set
    @Synchronized fun disconnect() { epoch++; blocked = true }
    @Synchronized fun explicitPlay(): Long { blocked = false; return epoch }
    fun permits(request: Long) = request == epoch && !blocked
}
