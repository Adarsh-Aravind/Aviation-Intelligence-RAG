"""Home-server resilience: network outages must not permanently fail documents."""

import hashlib
import time
import uuid

import psycopg

from app.services import ingestion
from app.services.storage import TransientStorageError


def _queued_doc(container, data: bytes):
    doc_id = uuid.uuid4()
    container.store.create_document(
        doc_id=doc_id,
        title="Manual",
        description=None,
        original_filename="m.pdf",
        storage_path=f"{doc_id}.pdf",
        file_type="application/pdf",
        file_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    container.store.update_document(doc_id, status="queued")
    container.storage.objects[f"{doc_id}.pdf"] = data
    return doc_id


def test_network_error_keeps_document_queued_and_retries(fakes, pdf_bytes, monkeypatch):
    container, _ = fakes
    worker = container.worker
    monkeypatch.setattr(ingestion, "RETRY_BASE_S", 0.01)
    doc_id = _queued_doc(container, pdf_bytes)

    real_download = container.storage.download_to
    calls = {"n": 0}

    def flaky_download(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransientStorageError("network error during download: ConnectError")
        return real_download(*args, **kwargs)

    monkeypatch.setattr(container.storage, "download_to", flaky_download)

    worker.process(doc_id)  # internet "down"
    doc = container.store.get_document(doc_id)
    assert doc["status"] == "queued"
    assert "Waiting for network" in doc["error_message"]

    time.sleep(0.2)  # the retry timer re-enqueues the document
    assert worker._queue.get_nowait() == doc_id
    worker.process(doc_id)  # internet "back"
    doc = container.store.get_document(doc_id)
    assert doc["status"] == "ready" and doc["error_message"] is None


def test_database_outage_is_transient(fakes, pdf_bytes, monkeypatch):
    container, _ = fakes
    monkeypatch.setattr(ingestion, "RETRY_BASE_S", 60)  # don't actually retry in this test
    doc_id = _queued_doc(container, pdf_bytes)

    def db_down(*args, **kwargs):
        raise psycopg.OperationalError("server closed the connection unexpectedly")

    monkeypatch.setattr(container.store, "insert_chunks", db_down)
    container.worker.process(doc_id)
    assert container.store.get_document(doc_id)["status"] == "queued"


def test_recover_requeues_documents_interrupted_by_power_cut(fakes, pdf_bytes):
    container, _ = fakes
    doc_id = _queued_doc(container, pdf_bytes)
    container.store.update_document(doc_id, status="processing")  # power cut mid-processing
    assert container.worker.recover() == 1
    assert container.store.get_document(doc_id)["status"] == "queued"
    container.worker.process(container.worker._queue.get_nowait())
    assert container.store.get_document(doc_id)["status"] == "ready"


def test_database_outage_returns_503_not_500(client, fakes, api_headers, monkeypatch):
    container, _ = fakes

    def db_down(*args, **kwargs):
        raise psycopg.OperationalError("could not translate host name")

    monkeypatch.setattr(container.store, "list_documents", db_down)
    r = client.get("/api/documents", headers=api_headers)
    assert r.status_code == 503
    assert "temporarily unreachable" in r.json()["detail"]
