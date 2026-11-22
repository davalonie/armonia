package com.armonia.app.playback

import android.app.usage.NetworkStats
import android.app.usage.NetworkStatsManager
import android.content.Context
import android.net.ConnectivityManager
import android.os.Process
import java.util.Calendar

/**
 * What this app moved this calendar month, as Android counts it (the same figures as the phone's data usage
 * settings, Tailscale's tunnel included in the app's share). Any app may read its own figures without a
 * permission. Null when the phone does not say.
 */
object DataUsage {
    data class Month(val mobileBytes: Long, val wifiBytes: Long)

    fun monthStart(now: Long): Long = Calendar.getInstance().apply {
        timeInMillis = now
        set(Calendar.DAY_OF_MONTH, 1)
        set(Calendar.HOUR_OF_DAY, 0)
        set(Calendar.MINUTE, 0)
        set(Calendar.SECOND, 0)
        set(Calendar.MILLISECOND, 0)
    }.timeInMillis

    fun thisMonth(context: Context, now: Long = System.currentTimeMillis()): Month? = runCatching {
        val stats = context.getSystemService(NetworkStatsManager::class.java) ?: return null
        val start = monthStart(now)
        @Suppress("DEPRECATION")
        Month(own(stats, ConnectivityManager.TYPE_MOBILE, start, now), own(stats, ConnectivityManager.TYPE_WIFI, start, now))
    }.getOrNull()

    private fun own(manager: NetworkStatsManager, type: Int, start: Long, end: Long): Long {
        val uid = Process.myUid()
        val summary = manager.querySummary(type, null, start, end)
        var total = 0L
        try {
            val bucket = NetworkStats.Bucket()
            while (summary.hasNextBucket()) {
                summary.getNextBucket(bucket)
                if (bucket.uid == uid) total += bucket.rxBytes + bucket.txBytes
            }
        } finally {
            summary.close()
        }
        return total
    }
}
