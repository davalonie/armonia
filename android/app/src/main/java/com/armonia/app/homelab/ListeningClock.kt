package com.armonia.app.homelab

/** Monotonic elapsed time plus plausible audio progress; seeking cannot count. */
class ListeningClock {
    var heardMs: Long = 0; private set
    private var position: Long? = null
    private var time: Long = 0
    fun sample(positionMs: Long, elapsedMs: Long, playing: Boolean, discontinuity: Boolean = false) {
        val prior=position
        if (prior!=null && playing && !discontinuity) {
            val wall=(elapsedMs-time).coerceAtLeast(0)
            val delta=positionMs-prior
            if(delta>0 && delta<=wall*2+500) heardMs+=minOf(delta,wall)
        }
        position=if(playing && !discontinuity) positionMs else null
        time=elapsedMs
    }
}
