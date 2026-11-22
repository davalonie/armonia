package com.armonia.app.playback

import android.net.Uri
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.TransferListener

/** External streaming is not automatically persisted in the LRU cache. */
class SourceRoutingDataSource(private val local:DataSource.Factory,private val external:DataSource.Factory):DataSource {
    private var delegate:DataSource?=null
    private val listeners=mutableListOf<TransferListener>()
    override fun addTransferListener(listener:TransferListener){listeners.add(listener);delegate?.addTransferListener(listener)}
    override fun open(dataSpec:DataSpec):Long {
        val factory=if(dataSpec.uri.path?.startsWith("/api/stream/")==true) local else external
        val source=factory.createDataSource();delegate=source;listeners.forEach{source.addTransferListener(it)}
        return source.open(dataSpec)
    }
    override fun read(buffer:ByteArray,offset:Int,length:Int):Int=checkNotNull(delegate).read(buffer,offset,length)
    override fun getUri():Uri?=delegate?.uri
    override fun getResponseHeaders():Map<String,List<String>> = delegate?.responseHeaders?:emptyMap()
    override fun close(){delegate?.close();delegate=null}
}
