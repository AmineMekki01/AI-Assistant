from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web

from app.api import routes
from app.api.handlers import health, google, settings, speaker, storage, system
from app.core import config as config_module
from app.services import google_auth as google_auth_module


class FakeRequest:
    def __init__(self, payload=None, remote="127.0.0.1", query=None):
        self._payload = payload or {}
        self.remote = remote
        self.query = query or {}

    async def json(self):
        return self._payload


class BrokenRequest:
    async def json(self):
        raise ValueError("broken request")


class FakeMultipartField:
    def __init__(self, name, value=None, filename=None, payload: bytes = b""):
        self.name = name
        self.filename = filename
        self._value = value
        self._payload = payload
        self._offset = 0

    async def text(self):
        return str(self._value or "")

    async def read_chunk(self, size=8192):
        if self._offset >= len(self._payload):
            return b""
        chunk = self._payload[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk


class FakeMultipartReader:
    def __init__(self, fields):
        self.fields = list(fields)
        self.index = 0

    async def next(self):
        if self.index >= len(self.fields):
            return None
        field = self.fields[self.index]
        self.index += 1
        return field


class FakeMultipartRequest(FakeRequest):
    def __init__(self, fields, remote="127.0.0.1"):
        super().__init__(payload={}, remote=remote)
        self.content_type = "multipart/form-data"
        self._fields = fields

    async def multipart(self):
        return FakeMultipartReader(self._fields)


class FakeOAuthResponse:
    def __init__(self, status: int, payload=None, text: str = "bad request"):
        self.status = status
        self._payload = payload or {}
        self._text = text

    async def text(self):
        return self._text

    async def json(self):
        return self._payload


class FakeOAuthRequestContext:
    def __init__(self, response: FakeOAuthResponse):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeOAuthSession:
    def __init__(self, response: FakeOAuthResponse):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, url, data=None):
        self.calls.append({"url": url, "data": data})
        return FakeOAuthRequestContext(self.response)


class FakeSystemResponse:
    def __init__(self, status: int, payload):
        self.status = status
        self._payload = payload or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload


class FakeSystemSession:
    last_instance = None

    def __init__(self, geocode_payload=None, weather_payload=None):
        self.geocode_payload = geocode_payload or {}
        self.weather_payload = weather_payload or {}
        self.calls = []
        FakeSystemSession.last_instance = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url, timeout=None):
        self.calls.append({"url": url, "timeout": timeout})
        if "geocoding-api.open-meteo.com" in url:
            return FakeSystemResponse(200, self.geocode_payload)
        if "api.open-meteo.com" in url:
            return FakeSystemResponse(200, self.weather_payload)
        return FakeSystemResponse(404, {})


class FakeCredentials:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def to_json(self):
        return json.dumps(self.kwargs)


class FakeQdrantClient:
    last_instance = None

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        FakeQdrantClient.last_instance = self

    def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name="jarvis_knowledge")])


class FakeIndexingQdrantClient:
    last_instance = None

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.create_collection_calls = []
        self.upsert_calls = []
        FakeIndexingQdrantClient.last_instance = self

    def get_collections(self):
        return SimpleNamespace(collections=[])

    def create_collection(self, **kwargs):
        self.create_collection_calls.append(kwargs)

    def upsert(self, **kwargs):
        self.upsert_calls.append(kwargs)


class FakePointStruct:
    def __init__(self, id, vector, payload):
        self.id = id
        self.vector = vector
        self.payload = payload


class FakeOpenAIEmbeddings:
    def __init__(self):
        self.calls = []

    async def create(self, input, model):
        self.calls.append({"input": input, "model": model})
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3]) for _ in input]
        )


class FakeAsyncOpenAI:
    last_instance = None

    def __init__(self, api_key=None):
        self.api_key = api_key
        self.embeddings = FakeOpenAIEmbeddings()
        FakeAsyncOpenAI.last_instance = self


def _install_fake_qdrant_modules(monkeypatch, client_cls):
    qdrant_module = types.ModuleType("qdrant_client")
    qdrant_module.QdrantClient = client_cls
    models_module = types.ModuleType("qdrant_client.models")
    models_module.Distance = SimpleNamespace(COSINE="cosine")
    models_module.VectorParams = lambda **kwargs: kwargs
    models_module.PointStruct = FakePointStruct
    monkeypatch.setitem(sys.modules, "qdrant_client", qdrant_module)
    monkeypatch.setitem(sys.modules, "qdrant_client.models", models_module)


def _install_fake_openai_module(monkeypatch):
    openai_module = types.ModuleType("openai")
    openai_module.AsyncOpenAI = FakeAsyncOpenAI
    monkeypatch.setitem(sys.modules, "openai", openai_module)


@pytest.mark.asyncio
async def test_health_handler_returns_ok():
    response = await health.handle_health(FakeRequest(remote="test-client"))
    assert response.status == 200
    assert json.loads(response.text) == {"status": "ok", "service": "jarvis-api"}


@pytest.mark.asyncio
async def test_settings_handlers_save_and_load(temp_home):
    payload = {"personal": {"name": "Amine"}, "appleCalendar": {"enabled": True}}
    save_response = await settings.handle_save_settings(FakeRequest(payload=payload))
    assert save_response.status == 200
    assert json.loads(save_response.text) == {"success": True}

    loaded = await settings.handle_load_settings(FakeRequest())
    assert json.loads(loaded.text) == payload


@pytest.mark.asyncio
async def test_speaker_profile_handlers_status_enroll_and_clear(temp_home, monkeypatch):
    profile_path = temp_home / ".jarvis" / "voice" / "speaker_profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps({"embeddings": [[1.0, 0.0, 0.0]], "threshold": 0.42, "model_name": "fake-model"}))

    settings_snapshot = SimpleNamespace(
        speaker_verification_enabled=True,
        speaker_profile_path=str(profile_path),
        speaker_verification_threshold=0.42,
        speaker_verification_model_name="fake-model",
    )
    monkeypatch.setattr(config_module, "get_settings", lambda: settings_snapshot)
    monkeypatch.setattr(speaker, "get_settings", lambda: settings_snapshot)

    def fake_enroll(cls, audio_paths, profile_path=None, threshold=0.35):
        return SimpleNamespace(
            embeddings=[[1.0, 0.0, 0.0]],
            threshold=threshold,
            model_name="fake-model",
            created_at="2026-05-16T00:00:00Z",
        )

    monkeypatch.setattr(speaker.SpeakerVerifier, "enroll_from_audio_paths", classmethod(fake_enroll))

    status_response = await speaker.handle_speaker_profile_status(FakeRequest())
    status_payload = json.loads(status_response.text)
    assert status_payload["profileExists"] is True
    assert status_payload["embeddingCount"] == 1
    assert status_payload["verificationEnabled"] is True

    enroll_response = await speaker.handle_speaker_profile_enroll(
        FakeMultipartRequest([
            FakeMultipartField("threshold", value="0.5"),
            FakeMultipartField("audio", filename="sample.wav", payload=b"fake-wav-data"),
        ])
    )
    enroll_payload = json.loads(enroll_response.text)
    assert enroll_payload["success"] is True
    assert enroll_payload["profile"]["profilePath"] == str(profile_path)
    assert enroll_payload["profile"]["verificationEnabled"] is True
    assert enroll_payload["profile"]["embeddingCount"] == 1

    clear_response = await speaker.handle_speaker_profile_clear(FakeRequest())
    clear_payload = json.loads(clear_response.text)
    assert clear_payload["success"] is True
    assert clear_payload["removed"] is True
    assert not profile_path.exists()


@pytest.mark.asyncio
async def test_google_status_reports_connected_when_token_exists(temp_home, monkeypatch):
    token_file = temp_home / ".jarvis" / "google_token.json"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("{}");
    monkeypatch.setattr(google, "token_path", lambda: token_file)
    monkeypatch.setattr(google, "load_google_credentials", lambda path, repair=False: (SimpleNamespace(), False))

    response = await google.handle_google_status(FakeRequest())
    payload = json.loads(response.text)
    assert payload["connected"] is True
    assert payload["lastConnected"] is not None


@pytest.mark.asyncio
async def test_google_status_reports_disconnected_without_token(temp_home, monkeypatch):
    token_file = temp_home / ".jarvis" / "google_token.json"
    monkeypatch.setattr(google, "token_path", lambda: token_file)

    response = await google.handle_google_status(FakeRequest())
    payload = json.loads(response.text)
    assert payload == {"connected": False, "lastConnected": None}


@pytest.mark.asyncio
async def test_google_disconnect_clears_token_file(temp_home, monkeypatch):
    token_file = temp_home / ".jarvis" / "google_token.json"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("{}")
    monkeypatch.setattr(google, "token_path", lambda: token_file)

    response = await google.handle_google_disconnect(FakeRequest())
    payload = json.loads(response.text)

    assert payload == {"connected": False, "removed": True}
    assert not token_file.exists()


@pytest.mark.asyncio
async def test_google_status_reports_invalid_token_when_loading_fails(temp_home, monkeypatch):
    token_file = temp_home / ".jarvis" / "google_token.json"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("{}")
    monkeypatch.setattr(google, "token_path", lambda: token_file)

    def raise_error(*args, **kwargs):
        raise ValueError("bad token")

    monkeypatch.setattr(google, "load_google_credentials", raise_error)

    response = await google.handle_google_status(FakeRequest())
    payload = json.loads(response.text)
    assert payload == {"connected": False, "lastConnected": None}


@pytest.mark.asyncio
async def test_oauth_callback_requires_authorization_code():
    response = await google.handle_oauth_callback(FakeRequest(query={}))
    assert response.status == 400
    assert json.loads(response.text)["error"] == "No authorization code received"


@pytest.mark.asyncio
async def test_oauth_callback_reports_exchange_failure(temp_home, monkeypatch):
    monkeypatch.setattr(config_module, "get_settings", lambda: SimpleNamespace(
        google_client_id="client-id",
        google_client_secret="client-secret",
    ))
    monkeypatch.setattr(google, "token_path", lambda: temp_home / ".jarvis" / "google_token.json")

    session = FakeOAuthSession(FakeOAuthResponse(400, text="invalid_grant"))
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: session)

    response = await google.handle_oauth_callback(FakeRequest(query={"code": "abc", "state": "s"}))
    assert response.status == 400
    assert json.loads(response.text)["error"] == "Token exchange failed"
    assert session.calls[0]["url"] == "https://oauth2.googleapis.com/token"


@pytest.mark.asyncio
async def test_oauth_callback_saves_tokens_and_redirects(temp_home, monkeypatch):
    token_file = temp_home / ".jarvis" / "google_token.json"
    monkeypatch.setattr(config_module, "get_settings", lambda: SimpleNamespace(
        google_client_id="client-id",
        google_client_secret="client-secret",
    ))
    monkeypatch.setattr(google, "token_path", lambda: token_file)
    monkeypatch.setattr(google, "Credentials", FakeCredentials)
    monkeypatch.setattr(google, "_GOOGLE_AVAILABLE", True)

    session = FakeOAuthSession(
        FakeOAuthResponse(
            200,
            {
                "access_token": "access-123",
                "refresh_token": "refresh-123",
                "scope": "scope.one scope.two",
            },
        )
    )
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: session)

    with pytest.raises(web.HTTPFound) as exc:
        await google.handle_oauth_callback(FakeRequest(query={"code": "abc", "state": "s"}))

    assert exc.value.location == "/auth/success"
    saved = json.loads(token_file.read_text())
    assert saved["token"] == "access-123"
    assert saved["refresh_token"] == "refresh-123"
    assert session.calls[0]["data"]["grant_type"] == "authorization_code"


@pytest.mark.asyncio
async def test_auth_success_returns_html_page():
    response = await google.handle_auth_success(FakeRequest())
    assert response.content_type == "text/html"
    assert "Google Account Connected!" in response.text


@pytest.mark.asyncio
async def test_dashboard_health_aggregates_cached_statuses(temp_home, monkeypatch):
    jarvis_dir = temp_home / ".jarvis"
    jarvis_dir.mkdir(parents=True, exist_ok=True)

    (jarvis_dir / "qdrant_status.json").write_text(json.dumps({
        "connected": True,
        "collectionExists": True,
        "host": "localhost",
        "port": 6333,
        "collectionName": "jarvis_knowledge",
    }))
    (jarvis_dir / "obsidian_status.json").write_text(json.dumps({"synced": True, "lastSync": 123.0, "fileCount": 5}))
    (jarvis_dir / "zimbra_status.json").write_text(json.dumps({"configured": True, "ok": True, "lastTested": 456.0}))
    (jarvis_dir / "apple_calendar_status.json").write_text(json.dumps({"enabled": True, "available": True, "ok": True, "lastTested": 789.0}))

    token_file = jarvis_dir / "google_token.json"
    token_file.write_text("{}")
    monkeypatch.setattr(health.Path, "home", lambda: temp_home)
    monkeypatch.setattr(google_auth_module, "token_path", lambda: token_file)
    monkeypatch.setattr(google_auth_module, "load_google_credentials", lambda path, repair=False: (SimpleNamespace(), False))
    _install_fake_qdrant_modules(monkeypatch, FakeQdrantClient)

    response = await health.handle_dashboard_health(FakeRequest())
    payload = json.loads(response.text)

    assert payload["status"] == "ok"
    assert payload["google"]["connected"] is True
    assert payload["qdrant"]["connected"] is True
    assert payload["obsidian"]["synced"] is True
    assert payload["zimbra"]["ok"] is True
    assert payload["appleCalendar"]["ok"] is True


@pytest.mark.asyncio
async def test_dashboard_health_probes_live_qdrant_connection(temp_home, monkeypatch):
    jarvis_dir = temp_home / ".jarvis"
    jarvis_dir.mkdir(parents=True, exist_ok=True)
    (jarvis_dir / "qdrant_status.json").write_text(json.dumps({
        "host": "localhost",
        "port": 6333,
        "collectionName": "jarvis_knowledge",
        "apiKey": None,
    }))

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name="jarvis_knowledge")])

    monkeypatch.setattr(health, "Path", health.Path)
    monkeypatch.setattr("qdrant_client.QdrantClient", FakeClient)

    response = await health.handle_dashboard_health(FakeRequest())
    payload = json.loads(response.text)

    assert payload["qdrant"]["connected"] is True
    assert payload["qdrant"]["collectionExists"] is True


@pytest.mark.asyncio
async def test_system_metrics_returns_real_location_and_weather(temp_home, monkeypatch):
    jarvis_dir = temp_home / ".jarvis"
    jarvis_dir.mkdir(parents=True, exist_ok=True)
    (jarvis_dir / "settings.json").write_text(json.dumps({
        "personal": {
            "defaultLocation": "New York, NY",
            "preferences": {"temperatureUnit": "fahrenheit"}
        }
    }))

    monkeypatch.setattr(system.Path, "home", lambda: temp_home)
    fake_session = FakeSystemSession(
        geocode_payload={
            "results": [
                {
                    "name": "New York",
                    "admin1": "NY",
                    "country": "United States",
                    "latitude": 40.7128,
                    "longitude": -74.0060,
                }
            ]
        },
        weather_payload={
            "current": {
                "temperature_2m": 68.9,
                "weather_code": 1,
            }
        },
    )
    monkeypatch.setattr(system.aiohttp, "ClientSession", lambda: fake_session)

    response = await system.handle_system_metrics(FakeRequest())
    payload = json.loads(response.text)

    assert payload["status"] == "ok"
    assert payload["location"] == "New York, NY, United States"
    assert payload["temperature"] == 68.9
    assert payload["temperatureUnit"] == "fahrenheit"
    assert payload["condition"] == "Mostly clear"
    assert len(fake_session.calls) == 2


@pytest.mark.asyncio
async def test_system_metrics_handles_missing_location(temp_home, monkeypatch):
    jarvis_dir = temp_home / ".jarvis"
    jarvis_dir.mkdir(parents=True, exist_ok=True)
    (jarvis_dir / "settings.json").write_text(json.dumps({"personal": {"defaultLocation": ""}}))

    monkeypatch.setattr(system.Path, "home", lambda: temp_home)

    response = await system.handle_system_metrics(FakeRequest())
    payload = json.loads(response.text)

    assert payload["status"] == "missing_location"
    assert payload["temperature"] is None
    assert payload["location"] == "Set a default location in Personal settings"


@pytest.mark.asyncio
async def test_storage_helpers_and_routes(monkeypatch, temp_home):
    assert storage._chunk_text("") == []
    assert storage._chunk_text("one two") == ["one two"]

    response = await storage.handle_qdrant_status(FakeRequest())
    assert json.loads(response.text) == {"connected": False, "collectionExists": False}

    class FakeRouter:
        def __init__(self):
            self.calls = []

        def add_get(self, path, handler):
            self.calls.append(("GET", path, handler.__name__))

        def add_post(self, path, handler):
            self.calls.append(("POST", path, handler.__name__))

        def add_delete(self, path, handler):
            self.calls.append(("DELETE", path, handler.__name__))

    class FakeApp:
        def __init__(self):
            self.router = FakeRouter()

    fake_app = FakeApp()
    routes.register_routes(fake_app)
    paths = [path for _, path, _ in fake_app.router.calls]
    assert "/api/health" in paths
    assert "/api/health/dashboard" in paths
    assert "/api/system/metrics" in paths
    assert "/api/google/disconnect" in paths
    assert "/api/settings/load" in paths
    assert "/api/obsidian/sync" in paths
    assert ("GET", "/api/speaker/profile", "handle_speaker_profile_status") in fake_app.router.calls
    assert ("POST", "/api/speaker/profile/enroll", "handle_speaker_profile_enroll") in fake_app.router.calls
    assert ("DELETE", "/api/speaker/profile", "handle_speaker_profile_clear") in fake_app.router.calls


@pytest.mark.asyncio
async def test_qdrant_status_and_test_handlers(monkeypatch, temp_home):
    _install_fake_qdrant_modules(monkeypatch, FakeQdrantClient)

    status_file = temp_home / ".jarvis" / "qdrant_status.json"
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text(json.dumps({"host": "localhost", "port": 6333, "collectionName": "jarvis_knowledge"}))

    response = await storage.handle_qdrant_status(FakeRequest())
    payload = json.loads(response.text)
    assert payload == {"connected": True, "collectionExists": True}

    bad = await storage.handle_qdrant_test(BrokenRequest())
    assert bad.status == 400
    assert json.loads(bad.text)["error"] == "Invalid request"

    ok = await storage.handle_qdrant_test(FakeRequest(payload={"host": "localhost", "port": 6333, "collectionName": "jarvis_knowledge"}))
    assert json.loads(ok.text) == {"ok": True}
    saved = json.loads(status_file.read_text())
    assert saved["collectionName"] == "jarvis_knowledge"


@pytest.mark.asyncio
async def test_qdrant_test_reports_backend_errors(monkeypatch):
    class RaisingQdrantClient:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    _install_fake_qdrant_modules(monkeypatch, RaisingQdrantClient)

    response = await storage.handle_qdrant_test(
        FakeRequest(payload={"host": "localhost", "port": 6333, "collectionName": "jarvis_knowledge"})
    )
    payload = json.loads(response.text)

    assert response.status == 500
    assert payload["ok"] is False
    assert "connection refused" in payload["error"]


@pytest.mark.asyncio
async def test_obsidian_sync_validates_path_and_indexes_locally(temp_home, monkeypatch):
    vault = temp_home / "vault"
    vault.mkdir()
    notes_dir = vault / "notes"
    notes_dir.mkdir()
    (notes_dir / "first.md").write_text("# First\n\nThis is a note.")
    (notes_dir / ".hidden.md").write_text("hidden")

    invalid = await storage.handle_obsidian_sync(FakeRequest(payload={"vaultPath": "", "autoSync": True, "syncInterval": 15}))
    assert invalid.status == 400
    assert "Invalid vault path" in json.loads(invalid.text)["error"]

    empty_vault = temp_home / "empty-vault"
    empty_vault.mkdir()
    no_files = await storage.handle_obsidian_sync(FakeRequest(payload={"vaultPath": str(empty_vault)}))
    assert json.loads(no_files.text)["qdrantStatus"] == "No files to index"

    monkeypatch.setattr(config_module, "get_settings", lambda: SimpleNamespace(qdrant_url=None))
    response = await storage.handle_obsidian_sync(FakeRequest(payload={"vaultPath": str(vault), "autoSync": True, "syncInterval": 30}))
    payload = json.loads(response.text)
    assert payload["success"] is True
    assert payload["indexed"] >= 1
    assert payload["qdrantStatus"] == "Saved to local JSON"

    index_file = temp_home / ".jarvis" / "obsidian_index.json"
    status_file = temp_home / ".jarvis" / "obsidian_status.json"
    indexed = json.loads(index_file.read_text())
    assert indexed[0]["metadata"]["source"] == "obsidian"
    status = json.loads(status_file.read_text())
    assert status["vaultPath"] == str(vault)


@pytest.mark.asyncio
async def test_obsidian_sync_indexes_to_qdrant(monkeypatch, temp_home):
    vault = temp_home / "vault-qdrant"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("# Note\n\nThis note should be indexed.")

    _install_fake_qdrant_modules(monkeypatch, FakeIndexingQdrantClient)
    _install_fake_openai_module(monkeypatch)
    monkeypatch.setattr(config_module, "get_settings", lambda: SimpleNamespace(
        qdrant_url="http://qdrant.test",
        openai_api_key="openai-key",
    ))

    response = await storage.handle_obsidian_sync(FakeRequest(payload={"vaultPath": str(vault), "autoSync": False, "syncInterval": 15}))
    payload = json.loads(response.text)

    assert payload["success"] is True
    assert payload["qdrantStatus"] == "Indexed 1 chunks to Qdrant"

    client = FakeIndexingQdrantClient.last_instance
    assert client.kwargs["url"] == "http://qdrant.test"
    assert len(client.create_collection_calls) == 1
    assert len(client.upsert_calls) == 1
    assert client.upsert_calls[0]["collection_name"] == "obsidian_vault"
    assert client.upsert_calls[0]["points"][0].payload["title"] == "note"

    openai_client = FakeAsyncOpenAI.last_instance
    assert openai_client.api_key == "openai-key"
    assert openai_client.embeddings.calls[0]["model"] == "text-embedding-3-small"
