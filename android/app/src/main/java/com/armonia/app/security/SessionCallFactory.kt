package com.armonia.app.security

import com.armonia.app.data.repository.AuthSnapshot
import okhttp3.Call
import okhttp3.Request

/** Freeze the caller's account before OkHttp queues the request on its dispatcher. */
class SessionCallFactory(
    private val delegate: Call.Factory,
    private val account: () -> AuthSnapshot,
) : Call.Factory {
    override fun newCall(request: Request): Call {
        val captured = request.tag(AuthSnapshot::class.java) ?: account()
        return delegate.newCall(request.newBuilder().tag(AuthSnapshot::class.java, captured).build())
    }
}
