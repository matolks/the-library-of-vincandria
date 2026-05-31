import os
import voyageai

_client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
MODEL = "voyage-3.5-lite"

def embed_document(text: str) -> list[float]:
    r = _client.embed([text], model=MODEL, input_type="document")
    return r.embeddings[0]

def embed_documents(texts: list[str]) -> list[list[float]]:
    # Voyage allows up to 128 inputs per call; chunk if larger
    out = []
    for i in range(0, len(texts), 128):
        r = _client.embed(texts[i:i+128], model=MODEL, input_type="document")
        out.extend(r.embeddings)
    return out

def embed_query(text: str) -> list[float]:
    r = _client.embed([text], model=MODEL, input_type="query")
    return r.embeddings[0]