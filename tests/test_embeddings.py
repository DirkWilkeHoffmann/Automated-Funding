"""Unit tests for the discovery embedding wrapper (mocked OpenAI client)."""
import utils.discovery.embeddings as emb


class _FakeEmbeddings:
    def __init__(self, dim):
        self._dim = dim

    def create(self, model, input):
        # Mirror openai's response shape: .data is a list of objects with .embedding
        class _Item:
            def __init__(self, vec):
                self.embedding = vec

        class _Resp:
            pass

        r = _Resp()
        r.data = [_Item([0.1] * self._dim) for _ in input]
        return r


class _FakeClient:
    def __init__(self, dim=1536):
        self.embeddings = _FakeEmbeddings(dim)


def test_embed_text_returns_vector(monkeypatch):
    monkeypatch.setattr(emb, "get_client", lambda: _FakeClient())
    vec = emb.embed_text("children youth education")
    assert isinstance(vec, list)
    assert len(vec) == 1536


def test_embed_batch_preserves_order_and_count(monkeypatch):
    monkeypatch.setattr(emb, "get_client", lambda: _FakeClient())
    out = emb.embed_batch(["a", "b", "c"])
    assert len(out) == 3
    assert all(len(v) == 1536 for v in out)


def test_embed_text_returns_none_without_client(monkeypatch):
    monkeypatch.setattr(emb, "get_client", lambda: None)
    assert emb.embed_text("x") is None


def test_embed_batch_skips_empty_strings(monkeypatch):
    monkeypatch.setattr(emb, "get_client", lambda: _FakeClient())
    out = emb.embed_batch(["", "real", "   "])
    # Empty/whitespace inputs map to None; real text gets a vector.
    assert out[0] is None
    assert out[1] is not None and len(out[1]) == 1536
    assert out[2] is None
