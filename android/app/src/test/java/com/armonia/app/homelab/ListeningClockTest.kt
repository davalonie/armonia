package com.armonia.app.homelab
import org.junit.Assert.*
import org.junit.Test
class ListeningClockTest {
    @Test fun mixedContextKeepsExternalReference(){assertEquals("external|fixture",com.armonia.app.playback.realTrackId("track|mixed|playlist|external|fixture"))}
    @Test fun navidromeIdentifiersSurviveQueueConversion(){
        val id="11111111-1111-4111-8111-111111111111"
        val s=MusicTrack("navidrome","song","Song","Artist").toSong().copy(musicTrack=null,
            musicBrainzId=id,artists=listOf(com.armonia.app.data.api.SongArtistRef("Artist",id)))
        assertEquals(id,s.asMusicTrack().recordingMbid)
        assertEquals(listOf(id),s.asMusicTrack().artistMbids)
    }
    @Test fun seekAndStallNeverCount(){val c=ListeningClock();c.sample(0,0,true);c.sample(100000,1000,true,true);c.sample(100000,5000,true);c.sample(100000,9000,true);assertEquals(0,c.heardMs)}
    @Test fun pauseTimeIsExcluded(){val c=ListeningClock();c.sample(0,0,true);c.sample(5000,5000,true);c.sample(5000,6000,false);c.sample(5000,90000,true);c.sample(10000,95000,true);assertEquals(10000,c.heardMs)}
    @Test fun rateCannotManufactureWallTime(){val c=ListeningClock();for(i in 0L..100L)c.sample(i*2000,i*1000,true);assertEquals(100000,c.heardMs)}
    @Test fun referenceNeverContainsProviderUrl(){val t=MusicTrack("authorized_http","fixture","Song","Artist");assertEquals("external|fixture",t.toSong().id);assertEquals(t,t.toSong().asMusicTrack())}
}
