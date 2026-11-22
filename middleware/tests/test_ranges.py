import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from auth import get_current_session
from routes import library, stream
from services.http_ranges import single_range


@pytest.mark.parametrize('value', ['bytes=0-', 'bytes=0-10', 'bytes=-100', None])
def test_supported_ranges(value):
    assert single_range(value) == value


@pytest.mark.parametrize('value', ['bytes=1-0','bytes=-','bytes=-0','bytes=0-1,2-3','bytes=+1-2',
    'items=0-1','bytes=9999999999999999999-', 'bytes=0-' + '1'*100])
def test_invalid_ranges(value):
    with pytest.raises(HTTPException) as exc:
        single_range(value)
    assert exc.value.status_code == 416


def test_multirange_never_reaches_navidrome(monkeypatch):
    app = FastAPI()
    app.include_router(stream.router)
    app.include_router(library.router)
    app.dependency_overrides[get_current_session] = lambda: {'username':'alice','salt':'s','token':'t'}
    def forbidden(**kw):
        raise AssertionError('invalid media request reached downstream')
    monkeypatch.setattr(stream.httpx, 'AsyncClient', forbidden)
    with TestClient(app) as c:
        assert c.get('/api/stream/track',headers={'Range':'bytes=0-1,2-3'}).status_code == 416
        assert c.get('/api/library/download',params={'id':'track'}).status_code == 400
        assert c.get('/api/library/stream.view',params={'id':'track'}).status_code == 400
