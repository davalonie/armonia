import asyncio
from threading import Event

from routes import search


def test_songs_are_available_while_artists_wait_and_cache_is_per_session(monkeypatch):
    search._results.clear()
    started, release = Event(), Event()
    calls = []

    def songs(query, limit, source):
        calls.append(query)
        return [{"title": "Mar"}]

    def artists(query, limit):
        started.set()
        assert release.wait(timeout=5)
        return [{"name": "Ana"}]

    monkeypatch.setattr(search.ytdlp_service, "search", songs)
    monkeypatch.setattr(search.ytdlp_service, "search_artists", artists)

    async def check():
        def ask(scope, user="a"):
            return search.search(search.SearchRequest(query="Mar", scope=scope), {"id": user})
        pending = asyncio.create_task(ask("all"))
        try:
            assert await asyncio.to_thread(started.wait, 3)
            got, repeated = await asyncio.wait_for(asyncio.gather(ask("songs"), ask("songs")), 2)
            assert got == repeated == {"artists": [], "songs": [{"title": "Mar"}]}
            assert not pending.done() and calls == ["Mar"]
        finally:
            release.set()
        assert (await pending)["artists"] == [{"name": "Ana"}]
        await ask("songs", "b")
        assert len(calls) == 2
    asyncio.run(check())


def test_empty_external_results_are_retryable(monkeypatch):
    search._results.clear()
    answers = iter([[], ["found"]])
    monkeypatch.setattr(search.ytdlp_service, "search", lambda *args: next(answers))
    req = search.SearchRequest(query="Faro", source="youtube")
    assert asyncio.run(search.search(req, {"id": "a"}))["songs"] == []
    assert asyncio.run(search.search(req, {"id": "a"}))["songs"] == ["found"]
