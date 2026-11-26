package com.armonia.app

import android.content.Context
import android.content.Intent

/**
 * The app's own way in, as the launcher opens it (web.LaunchActivity). The core (notifications,
 * Android Auto, the sign-in return) opens the app through here. A task that is already open is
 * brought to the front.
 */
object AppEntry {
    fun intent(context: Context): Intent =
        requireNotNull(context.packageManager.getLaunchIntentForPackage(context.packageName)) { "Sin actividad de entrada" }

    /**
     * Starts again from the entry with nothing of the previous screens left: after signing in, or when
     * the session is gone. (The launcher intent alone would only bring an open task to the front.)
     */
    fun restart(context: Context) {
        context.startActivity(intent(context).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
    }
}
