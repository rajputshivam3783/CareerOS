"""Small dependency-free TF-IDF helpers used by matching and search."""

import math
import re
from collections import Counter


_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to",
    "was", "with",
}


def _tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", value.lower()) if token not in _STOP_WORDS]


def _vectors(documents: list[str]) -> list[dict[str, float]]:
    tokenized = [_tokens(document) for document in documents]
    document_frequency = Counter(token for document in tokenized for token in set(document))
    total_documents = len(tokenized)
    vectors = []
    for document in tokenized:
        counts = Counter(document)
        vector = {
            token: (count / len(document)) * math.log((1 + total_documents) / (1 + document_frequency[token]))
            for token, count in counts.items()
        } if document else {}
        vectors.append(vector)
    return vectors


def similarity_scores(query: str, documents: list[str]) -> list[float]:
    vectors = _vectors([query, *documents])
    query_vector = vectors[0]
    query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
    scores = []
    for document_vector in vectors[1:]:
        document_norm = math.sqrt(sum(value * value for value in document_vector.values()))
        shared = set(query_vector) & set(document_vector)
        denominator = query_norm * document_norm
        scores.append(sum(query_vector[token] * document_vector[token] for token in shared) / denominator if denominator else 0.0)
    return scores
