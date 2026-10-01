from uuid import uuid4

from app.models.domain import Chunk
from app.services.rag import INSUFFICIENT_MESSAGE, RagService, build_user_prompt, extract_citations
from app.services.retrieval import Retriever
from tests.conftest import FakeEmbedder, FakeLLM, FakeStore


def _seed(store: FakeStore, embedder: FakeEmbedder, texts: list[tuple[str, int]], title="PHAK"):
    doc_id = uuid4()
    store.docs[doc_id] = {"id": doc_id, "title": title, "status": "ready", "sha256": "x"}
    chunks = [Chunk(i, t, p, p, section=None) for i, (t, p) in enumerate(texts)]
    store.insert_chunks(doc_id, chunks, embedder.embed_documents([c.content for c in chunks]))
    return doc_id


def _service(reply="Answer [1].", min_relevance=0.2):
    store, emb, llm = FakeStore(), FakeEmbedder(), FakeLLM(reply)
    _seed(
        store,
        emb,
        [
            ("Density altitude is pressure altitude corrected for nonstandard temperature.", 12),
            ("Stall recovery: reduce angle of attack, level wings, add power.", 40),
        ],
    )
    return (
        RagService(Retriever(store, emb, candidates=10, top_k=4, min_relevance=min_relevance), llm),
        store,
        llm,
    )


# ---------------------------------------------------------------- retrieval
def test_retrieval_ranks_relevant_chunk_first():
    rag, _, _ = _service()
    result = rag.retriever.retrieve("What is density altitude and temperature?")
    assert result.chunks[0].page_start == 12
    assert result.chunks[0].score >= result.chunks[-1].score


def test_retrieval_ignores_documents_not_ready():
    rag, store, _ = _service()
    for d in store.docs.values():
        d["status"] = "processing"
    assert rag.retriever.retrieve("density altitude").chunks == []


def test_retrieval_dedupes_same_passage_across_documents():
    rag, store, _ = _service()
    _seed(store, rag.retriever.embedder, [("Density altitude is pressure altitude corrected for nonstandard temperature.", 3)], title="Copy")
    chunks = rag.retriever.retrieve("What is density altitude?").chunks
    assert sum("Density altitude" in c.content for c in chunks) == 1


def test_retrieval_applies_threshold():
    rag, _, _ = _service(min_relevance=0.99)
    assert rag.retriever.retrieve("density altitude").chunks == []


# ---------------------------------------------------------------- grounding
def test_irrelevant_question_short_circuits_without_llm():
    rag, _, llm = _service()
    resp = rag.answer("best pizza restaurant in Rome")
    assert resp.status == "insufficient_context"
    assert resp.answer == INSUFFICIENT_MESSAGE
    assert resp.grounded is False and resp.citations == []
    assert llm.calls == []  # never asked the LLM


def test_answer_with_valid_citation_is_grounded():
    rag, _, llm = _service(reply="Density altitude is corrected pressure altitude [1].")
    resp = rag.answer("What is density altitude?")
    assert resp.status == "answered" and resp.grounded
    assert [c.n for c in resp.citations] == [1]
    assert resp.citations[0].page_start == 12
    assert "Density altitude" in llm.calls[0][1]  # source text sent to the LLM
    assert resp.model == "fake-llm"


def test_llm_sentinel_maps_to_insufficient_context():
    rag, _, _ = _service(reply="INSUFFICIENT_CONTEXT")
    resp = rag.answer("What is density altitude?")
    assert resp.status == "insufficient_context"
    assert resp.answer == INSUFFICIENT_MESSAGE
    assert resp.citations == [] and resp.retrieved  # shows what was looked at


def test_uncited_answer_flagged_ungrounded():
    rag, _, _ = _service(reply="Density altitude is a thing pilots care about.")
    resp = rag.answer("What is density altitude?")
    assert resp.status == "answered"
    assert resp.grounded is False
    assert resp.citations == []


def test_extract_citations_drops_invalid_numbers():
    text, cited = extract_citations("Fact A [1]. Fact B [7]. Fact C [2, 9][1].", num_sources=2)
    assert cited == [1, 2]
    assert "[7]" not in text and "[9]" not in text
    assert text == "Fact A [1]. Fact B. Fact C [2][1]."


def test_alternative_citation_styles_are_normalised():
    text, cited = extract_citations("A 【1】. B【2†L3-L5】. C [1†source]. D 【1, 2】.", num_sources=2)
    assert cited == [1, 2]
    assert text == "A [1]. B[2]. C [1]. D [1][2]."


def test_prompt_numbers_sources_with_pages():
    rag, store, _ = _service()
    chunks = rag.retriever.retrieve("density altitude").chunks
    prompt = build_user_prompt("Q?", chunks)
    assert prompt.startswith("<sources>")
    assert "[1] PHAK (p. 12)" in prompt
    assert prompt.rstrip().endswith("Question: Q?")


def test_keyword_queries_strip_search_operators():
    from app.db.repository import _keyword_queries

    all_q, any_q = _keyword_queries('VFR -minimums "Class C" OR (airspace) & !x')
    assert all_q == "VFR minimums Class C OR airspace x"
    assert any_q == "VFR or minimums or Class or C or OR or airspace or x"
    assert _keyword_queries("¿¡") == ("", "")


def test_hybrid_keeps_fused_order_and_cosine_gate():
    rag, store, _ = _service(min_relevance=0.2)
    chunks = rag.retriever.retrieve("density altitude temperature").chunks
    assert chunks and all(c.score >= 0.2 for c in chunks)
    assert {c.match for c in chunks} <= {"semantic", "keyword", "both"}
