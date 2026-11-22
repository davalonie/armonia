package com.armonia.app.ui.playlists

import com.google.gson.Gson
import com.armonia.app.homelab.*
import org.junit.Assert.*
import org.junit.Test

class ImportReviewQueueTest {
    private fun item(state:String,order:Long=0)=ImportItem(
        Recording("Fixture", "Artist"),state,emptyList(),null,null,choiceRevision=7,reviewOrder=order,
    )
    private fun job(items:List<ImportItem>,status:String="running",accepting:Boolean?=true)=ImportJob(
        "fixture","Fixture",status,42,items.size,0,0,0,0,items,null,null,accepting,
    )

    @Test fun confirmationDisappearsWhileOtherChoicesRemainEnabled() {
        val before=job(listOf(item("review"),item("review"),item("review")))
        val accepted=before.copy(items=listOf(item("pending"),item("review"),item("review")),revision=43)
        assertEquals(listOf(1,2),orderedImportReview(accepted).map{it.index})
        assertTrue(canDecideImportItem(accepted,accepted.items[1]))
        assertFalse(canDecideImportItem(accepted,accepted.items[0]))
        assertEquals(1,nextImportReviewIndex(listOf(0,1,2),listOf(1,2),0))
    }

    @Test fun failuresReturnAtTheEndWithoutChangingApiPositions() {
        val items=listOf(item("download_failed",88),item("review"),item("download_failed",91),item("review"))
        val result=orderedImportReview(job(items)).map{it.index}
        assertEquals(listOf(1,3,0,2),result)
        assertEquals("download_failed",items[0].state)
        val localFailure=mapOf(1 to ImportDecisionFailure(100,"Could not confirm"))
        assertEquals(listOf(3,0,2,1),orderedImportReview(job(items),localFailure).map{it.index})
        assertEquals(3,nextImportReviewIndex(result,listOf(3,0,2),1))
    }

    @Test fun cancellationAndOlderServersDoNotEnableConcurrentChanges() {
        val review=item("review")
        assertFalse(canDecideImportItem(job(listOf(review),accepting=false),review))
        assertFalse(canDecideImportItem(job(listOf(review),accepting=null),review))
        assertTrue(canDecideImportItem(job(listOf(review),status="done",accepting=null),review))
        for(state in listOf("pending","searching","downloading","indexing","ready")){
            assertFalse(state,canDecideImportItem(job(listOf(item(state))),item(state)))
        }
        assertFalse(canDecideImportItem(job(listOf(item("ready")),status="done"),item("ready")))
    }

    @Test fun failedIndexingIsRecoverableWithoutAnAlternativeSearch() {
        val waiting=item("indexing",99).copy(reason="index_pending")
        assertTrue(orderedImportReview(job(listOf(waiting))).isEmpty())
        val stopped=job(listOf(waiting),status="done")
        assertEquals(listOf(0),orderedImportReview(stopped).map{it.index})
        assertTrue(canDecideImportItem(stopped,waiting))
        assertFalse(canSearchImportAlternatives(waiting.state))
        assertTrue(importFailureReason(waiting.reason).contains("no vuelve a descargarlo"))
    }

    @Test fun delayedSnapshotsCannotRestoreAnAcceptedChoiceOrSwitchImports() {
        assertTrue(acceptsImportSnapshot(2,2,"fixture","fixture",43,44))
        assertFalse(acceptsImportSnapshot(1,2,"fixture","fixture",43,42))
        assertFalse(acceptsImportSnapshot(2,2,"fixture","fixture",43,42))
        assertFalse(acceptsImportSnapshot(2,2,"another","fixture",null,100))
    }

    @Test fun additiveContractKeepsOldRepliesAndPerItemRevision() {
        val gson=Gson()
        val old=gson.fromJson("""{"track":{"title":"T","artist":"A"},"state":"review","candidates":[]}""",ImportItem::class.java)
        assertNull(old.choiceRevision)
        assertNull(old.reviewOrder)
        assertNull(old.manualPending)
        val body=gson.toJsonTree(ImportDecision(50,"confirm",5,"abcdefghijk",itemRevision=7)).asJsonObject
        assertEquals(7,body["itemRevision"].asInt)
        assertEquals(5,body["index"].asInt)
        assertEquals("abcdefghijk",body["source_id"].asString)
        assertFalse(gson.toJsonTree(ImportDecision(50,"resume")).asJsonObject.has("itemRevision"))
    }

    @Test fun errorReasonsNeverDisplayAnUpstreamUrl() {
        assertFalse(importFailureReason("https://provider.invalid/?secret=fictional").contains("secret"))
        assertTrue(importFailureReason("permission").contains("permiso"))
    }

    @Test fun skippedCardsMoveToInboxWithoutRenumberingReviewOrChangingCounts() {
        val entries = listOf(item("review"), item("skipped").copy(manualPending=true), item("review"))
        val updated = job(entries, status="done").copy(manualInboxAvailable=true)
        assertEquals(listOf(0,2), orderedImportReview(updated).map { it.index })
        assertEquals(1, ImportProgress.fromStates(updated.items.map { it.state }).skipped)
        assertEquals(2, nextImportReviewIndex(listOf(0,1,2),listOf(0,2),1))
        assertEquals(listOf(0,1,2), orderedImportReview(updated.copy(manualInboxAvailable=null)).map { it.index })
        assertEquals(listOf(0,1,2), orderedImportReview(updated.copy(manualInboxAvailable=false)).map { it.index })
    }

    @Test fun legacySkippedItemsRemainRecoverableEvenOnANewServer() {
        val entries=listOf(item("skipped"),item("skipped").copy(manualPending=false),item("skipped").copy(manualPending=true))
        val updated=job(entries,status="done").copy(manualInboxAvailable=true)
        assertEquals(listOf(0,1),orderedImportReview(updated).map { it.index })
        assertEquals(3,ImportProgress.fromStates(entries.map { it.state }).skipped)
        val parsed=Gson().fromJson("""{"track":{"title":"T","artist":"A"},"state":"skipped","candidates":[],"manualPending":true}""",ImportItem::class.java)
        assertEquals(true,parsed.manualPending)
    }

    @Test fun compatibleSourcesReasonIsAdditiveAndPreservesCandidateIdentity() {
        val parsed=Gson().fromJson("""{"track":{"title":"T","artist":"A"},"state":"review","candidates":[],"comparison_reason":"multiple_compatible_sources"}""",ImportItem::class.java)
        assertEquals("multiple_compatible_sources",parsed.comparisonReason)
        assertEquals("review",parsed.state)
    }
}
