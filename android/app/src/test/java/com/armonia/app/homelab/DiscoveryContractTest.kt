package com.armonia.app.homelab

import com.google.gson.Gson
import org.junit.Assert.*
import org.junit.Test

class DiscoveryContractTest {
    @Test fun `old and trending results have no personal provenance`() {
        val old=Gson().fromJson("""{"artists":[{"name":"Popular","sourceArtist":"Chart"}]}""",DiscoverResult::class.java)
        assertTrue(old.personalArtists().isEmpty())
        val mixed=Gson().fromJson("""{"version":1,"artists":[{"name":"Popular","provenance":"charts"}]}""",DiscoverResult::class.java)
        assertTrue(mixed.personalArtists().isEmpty())
    }
    @Test fun `identified seeds and unresolved profile survive shared contract`() {
        val result=Gson().fromJson("""{"version":1,"state":"ready","artists":[{"name":"Related","sourceArtist":"Private Seed","provenance":"similar_to_identified_seed","seeds":[{"name":"Private Seed","mbid":"id"}]}],"seeds":[{"name":"Unresolved","status":"ambiguous","reason":"multiple_artists"}]}""",DiscoverResult::class.java)
        assertEquals("Private Seed",result.personalArtists().single().sourceArtist)
        assertEquals("ambiguous",result.seeds!!.single().status)
        assertEquals("Hay varios artistas con ese nombre",result.seeds!!.single().explanation())
    }
}
