import asyncio

from homelab import import_search, matcher
from homelab.models import Track


def candidate(**kw):
    return Track(source='youtube',source_id='abcdefghijk',title='Song',artist='Alice',duration=200,**kw)


def test_identifier_can_bridge_incomplete_credits_but_not_conflicting_versions():
    wanted={'title':'Song','artist':'Alice, Bob','duration':200,'isrc':'ESAAA2600001'}
    assert matcher.rank(wanted,[candidate(isrc='ESAAA2600001')])['selected']
    assert not matcher.rank(wanted,[candidate(isrc='ESAAA2600002')])['selected']
    live=candidate(isrc='ESAAA2600001').model_copy(update={'title':'Song (Live)'})
    assert not matcher.rank(wanted,[live])['selected']


def test_explicit_featured_forms_and_missing_identity():
    wanted={'title':'Song','artist':'Alice, Bob','duration':200}
    for title in ['Song [feat. Bob]','Song featuring Bob','Song ft. Bob']:
        assert matcher.rank(wanted,[candidate().model_copy(update={'title':title})])['selected']
    assert not matcher.rank({'title':'Song','artist':'Unknown','duration':200},[
        candidate().model_copy(update={'artist':'Unknown'})])['selected']


def test_expansion_recovers_candidate_without_lowering_threshold_and_clear_match_shortcircuits(monkeypatch):
    queries=[]
    def search(query,**kw):
        queries.append(query)
        return [] if ',' in query else [{'videoId':'abcdefghijk','title':'Song','channel':'Alice, Bob','duration':200}]
    monkeypatch.setattr(import_search.ytdlp_service,'search',search)
    wanted={'title':'Song','artist':'Alice, Bob','duration':200}
    result=asyncio.run(import_search.resolve(wanted,lambda:None))
    assert result['selected'] and len(queries)==2
    monkeypatch.setattr(import_search.ytdlp_service,'search',lambda *a,**k:[{'videoId':'abcdefghijk','title':'Song','channel':'Alice, Bob','duration':200}])
    result=asyncio.run(import_search.resolve(wanted,lambda:None))
    assert len(result['attempts'])==1
