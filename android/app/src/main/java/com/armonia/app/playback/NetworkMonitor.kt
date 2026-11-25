package com.armonia.app.playback

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Build
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject
import javax.inject.Singleton
import java.util.concurrent.ConcurrentHashMap

/**
 * Whether the phone has any network at all. It says nothing about the server being reachable
 * (that is learnt from the requests themselves); it only lets playback stop waiting for a
 * connection that cannot come back by retrying.
 */
@Singleton
class NetworkMonitor @Inject constructor(@ApplicationContext context: Context) {
    private val _onlineFlow = MutableStateFlow(true)
    /** The same value as [online], for whoever has to follow its changes (the Capacitor screens). */
    val onlineFlow: StateFlow<Boolean> = _onlineFlow.asStateFlow()

    @Volatile var online: Boolean = true
        private set(value) { field = value; _onlineFlow.value = value }

    // The phone's physical networks. With Tailscale on, the default network is the VPN, which stays the
    // same when the phone moves from Wi-Fi to mobile data; PathRate needs the network underneath.
    private val physical = ConcurrentHashMap<Network, NetworkCapabilities>()

    init {
        val manager = context.getSystemService(ConnectivityManager::class.java)
        online = manager?.activeNetwork != null
        runCatching {
            manager?.registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) { online = true }
                override fun onLost(network: Network) { online = manager.activeNetwork != null }
            })
        }
        runCatching {
            // Listen only: this never asks Android to bring up or keep any network.
            val request = NetworkRequest.Builder()
                .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
                .build()
            manager?.registerNetworkCallback(request, object : ConnectivityManager.NetworkCallback() {
                override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                    physical[network] = caps
                    updatePath()
                }
                override fun onLost(network: Network) {
                    physical.remove(network)
                    updatePath()
                }
            })
        }
    }

    /** The network songs travel over (validated first, Wi-Fi before mobile data) and its first guess. */
    private fun updatePath() {
        val best = physical.entries.sortedWith(compareBy(
            { !it.value.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) },
            { !it.value.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) },
        )).firstOrNull()
        if (best == null) {
            PathRate.onNetwork(null, null)
            return
        }
        val caps = best.value
        val wifi = caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
        val cellular = caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)
        val signal = if (Build.VERSION.SDK_INT >= 29)
            caps.signalStrength.takeIf { it != NetworkCapabilities.SIGNAL_STRENGTH_UNSPECIFIED } else null
        val kind = if (wifi) "wifi" else if (cellular) "movil" else "otra"
        val metered = cellular || !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)
        PathRate.onNetwork("$kind:${best.key}", PathRate.guess(wifi, cellular, caps.linkDownstreamBandwidthKbps, signal), metered)
    }
}
