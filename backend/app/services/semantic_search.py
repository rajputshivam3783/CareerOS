"""V6 semantic search.

Honesty note on what "semantic" means here: this ranks jobs by TF-IDF
(term-frequency/inverse-document-frequency) cosine similarity to the
query — a classical statistical text-similarity technique. It handles
synonyms and paraphrasing far better than exact keyword `LIKE` search
(e.g. a query for "backend developer roles" will surface a posting
titled "Software Engineer — Server Side" if their descriptions share
enough vocabulary), but it is **not** a neural embedding model and
won't understand true semantic equivalence between totally
different wording with no shared vocabulary at all.

Upgrade path, if/when it's worth the dependency weight: swap
`_vectorize` for a call to a real embedding model (a local
sentence-transformers model, or a hosted embeddings API) and replace
TF-IDF vectors with those — `rank_by_similarity`'s calling contract
(list of (Job, score) tuples) wouldn't need to change.
"""

from app.models.domain import Job
from app.services.text_similarity import similarity_scores


def _job_document(job: Job) -> str:
    return " ".join(
        filter(
            None,
            [
                job.title,
                job.organization,
                job.department,
                job.description,
                job.qualification,
                job.category,
                job.selection_process,
                job.industry,
            ],
        )
    )


def rank_by_similarity(query: str, jobs: list[Job], top_k: int = 20) -> list[dict]:
    """Rank `jobs` by TF-IDF cosine similarity to `query`.

    Returns a list of ``{"job": Job, "score": float}`` sorted
    descending by score, capped at `top_k`. Jobs with zero vocabulary
    overlap with the query score 0.0 rather than being dropped, so the
    caller can decide its own relevance cutoff.
    """
    if not jobs or not query.strip():
        return []

    documents = [query] + [_job_document(job) for job in jobs]

    similarities = similarity_scores(query, documents[1:])

    ranked = sorted(zip(jobs, similarities), key=lambda pair: pair[1], reverse=True)
    return [{"job": job, "score": round(float(score), 4)} for job, score in ranked[:top_k]]


def text_similarity(a: str, b: str) -> float:
    """TF-IDF cosine similarity between two arbitrary free-text
    strings (as opposed to `rank_by_similarity`, which compares a
    query against structured Job records). Used by V8 resume-JD
    matching to compare a resume's text against a job's text with the
    same explainable method used for job search. Returns 0.0 for
    empty/blank input or when there's no shared vocabulary, rather
    than raising.
    """
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return 0.0

    try:
        return similarity_scores(a, [b])[0]
    except (IndexError, ValueError):
        return 0.0
