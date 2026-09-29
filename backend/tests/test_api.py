import hashlib

import pytest

from app.api.documents import sanitize_filename


def _init_body(data: bytes, **over):
    body = {
        "filename": "phak.pdf",
        "title": "Pilot's Handbook",
        "file_size": len(data),
        "content_type": "application/pdf",
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    body.update(over)
    return body


def _upload_and_process(client, fakes, admin_headers, data: bytes) -> str:
    container, _ = fakes
    r = client.post("/api/documents/init", json=_init_body(data), headers=admin_headers)
    assert r.status_code == 201, r.text
    doc = r.json()["document"]
    assert r.json()["upload_url"].startswith("https://storage.test/upload/")
    # simulate the browser's direct upload to storage
    container.storage.objects[f"{doc['id']}.pdf"] = data
    r = client.post(f"/api/documents/{doc['id']}/complete", headers=admin_headers)
    assert r.status_code == 202 and r.json()["status"] == "queued"
    # process synchronously instead of waiting for the thread
    from uuid import UUID

    container.worker.process(UUID(doc["id"]))
    return doc["id"]


# ------------------------------------------------------------------- auth
def test_health_is_public(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] is True and body["embedder_loaded"] is True
    assert body["status"] == "ok"


def test_api_key_required(client):
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/documents", headers={"X-API-Key": "wrong"}).status_code == 401


def test_admin_required_for_mutations(client, api_headers, pdf_bytes):
    assert (
        client.post("/api/documents/init", json=_init_body(pdf_bytes), headers=api_headers).status_code == 403
    )
    assert (
        client.delete("/api/documents/00000000-0000-0000-0000-000000000000", headers=api_headers).status_code
        == 403
    )


# ------------------------------------------------------------------- uploads
def test_full_ingestion_flow(client, fakes, admin_headers, api_headers, pdf_bytes):
    doc_id = _upload_and_process(client, fakes, admin_headers, pdf_bytes)
    doc = client.get(f"/api/documents/{doc_id}", headers=api_headers).json()
    assert doc["status"] == "ready", doc
    assert doc["page_count"] == 4 and doc["chunk_count"] > 0

    listing = client.get("/api/documents", headers=api_headers).json()
    assert listing["total"] == 1

    stats = client.get("/api/stats", headers=api_headers).json()
    assert stats["documents_total"] == 1 and stats["chunks_total"] == doc["chunk_count"]
    assert stats["pages_total"] == 4


def test_duplicate_upload_rejected(client, fakes, admin_headers, pdf_bytes):
    _upload_and_process(client, fakes, admin_headers, pdf_bytes)
    r = client.post("/api/documents/init", json=_init_body(pdf_bytes), headers=admin_headers)
    assert r.status_code == 409
    assert "already been uploaded" in r.json()["detail"]["message"]


@pytest.mark.parametrize(
    "override,code",
    [
        ({"filename": "malware.exe"}, 415),
        ({"content_type": "text/html"}, 415),
        ({"file_size": 6 * 1024 * 1024}, 413),
        ({"sha256": "nothex"}, 422),
    ],
)
def test_upload_validation(client, admin_headers, pdf_bytes, override, code):
    r = client.post("/api/documents/init", json=_init_body(pdf_bytes, **override), headers=admin_headers)
    assert r.status_code == code, r.text


def test_checksum_mismatch_fails_document(client, fakes, admin_headers, api_headers, pdf_bytes):
    container, _ = fakes
    r = client.post("/api/documents/init", json=_init_body(pdf_bytes), headers=admin_headers)
    doc_id = r.json()["document"]["id"]
    container.storage.objects[f"{doc_id}.pdf"] = pdf_bytes + b"tampered"
    client.post(f"/api/documents/{doc_id}/complete", headers=admin_headers)
    from uuid import UUID

    container.worker.process(UUID(doc_id))
    doc = client.get(f"/api/documents/{doc_id}", headers=api_headers).json()
    assert doc["status"] == "failed" and "checksum" in doc["error_message"]


def test_non_pdf_content_fails_document(client, fakes, admin_headers, api_headers):
    container, _ = fakes
    data = b"<html>not a pdf</html>"
    r = client.post("/api/documents/init", json=_init_body(data), headers=admin_headers)
    doc_id = r.json()["document"]["id"]
    container.storage.objects[f"{doc_id}.pdf"] = data
    client.post(f"/api/documents/{doc_id}/complete", headers=admin_headers)
    from uuid import UUID

    container.worker.process(UUID(doc_id))
    doc = client.get(f"/api/documents/{doc_id}", headers=api_headers).json()
    assert doc["status"] == "failed" and "not a valid PDF" in doc["error_message"]


def test_delete_removes_document_and_file(client, fakes, admin_headers, api_headers, pdf_bytes):
    container, _ = fakes
    doc_id = _upload_and_process(client, fakes, admin_headers, pdf_bytes)
    assert client.delete(f"/api/documents/{doc_id}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/documents/{doc_id}", headers=api_headers).status_code == 404
    assert f"{doc_id}.pdf" in container.storage.deleted
    assert container.store.chunks == {}


def test_file_url(client, fakes, admin_headers, api_headers, pdf_bytes):
    doc_id = _upload_and_process(client, fakes, admin_headers, pdf_bytes)
    r = client.get(f"/api/documents/{doc_id}/file-url", headers=api_headers)
    assert r.status_code == 200 and r.json()["url"].startswith("https://storage.test/read/")


def test_sanitize_filename():
    assert sanitize_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert sanitize_filename("C:\\Users\\me\\My <Manual>.pdf") == "My _Manual_.pdf"
    assert sanitize_filename("a\x00b\x1f.pdf") == "ab.pdf"
    assert len(sanitize_filename("x" * 400 + ".pdf")) == 150


# ------------------------------------------------------------------- chat
def test_chat_grounded_answer(client, fakes, admin_headers, api_headers, pdf_bytes):
    _, llm = fakes
    llm.reply = "Density altitude is pressure altitude corrected for temperature [1]."
    _upload_and_process(client, fakes, admin_headers, pdf_bytes)
    r = client.post("/api/chat", json={"question": "What is density altitude?"}, headers=api_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "answered" and body["grounded"] is True
    cite = body["citations"][0]
    assert cite["n"] == 1 and cite["document_title"] == "Pilot's Handbook"
    assert cite["page_start"] == 2  # density altitude lives on page 2 of the fixture


def test_chat_insufficient_context(client, fakes, admin_headers, api_headers, pdf_bytes):
    _, llm = fakes
    _upload_and_process(client, fakes, admin_headers, pdf_bytes)
    r = client.post("/api/chat", json={"question": "best pizza in Rome?"}, headers=api_headers)
    assert r.json()["status"] == "insufficient_context"
    assert llm.calls == []


def test_chat_validation(client, api_headers):
    r = client.post("/api/chat", json={"question": " "}, headers=api_headers)
    assert r.status_code == 422
    r = client.post("/api/chat", json={"question": "x" * 1001}, headers=api_headers)
    assert r.status_code == 422


def test_chat_rate_limited(client, api_headers):
    codes = [
        client.post(
            "/api/chat", json={"question": "hello there"}, headers={**api_headers, "X-Client-IP": "1.2.3.4"}
        ).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [200] * 10
    assert codes[10] == 429
