import os
import time
import openai
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Embeddings use Jina independently from the chat-model provider.
# Add JINA_API_KEY to .env; keep EURI_* for chat generation.
_client = OpenAI(
    api_key=os.environ["JINA_API_KEY"],
    base_url=os.environ.get("JINA_BASE_URL", "https://api.jina.ai/v1"),
)
_EMBED_MODEL = os.environ.get("JINA_EMBED_MODEL", "jina-embeddings-v3")

BATCH_LIMIT = 20
# Keep requests below the Gemini free-tier embedding-token limit.
# The documents are about 1,500 characters per chunk, so 40 chunks is
# substantially safer than sending 100 chunks in one request.

MAX_EMBED_RETRIES = 5
# retry count for rate-limit / transient errors during embedding


class EuriEmbedder:
    # Single client wrapper so ingestion and query-time embedding always use the same model
    def __call__(self, texts: list[str], on_progress=None) -> list[list[float]]:
        all_vectors = []
        total_batches = (len(texts) + BATCH_LIMIT - 1) // BATCH_LIMIT
        # rounds up, so a partial last batch still counts as one full batch

        for batch_num, start in enumerate(range(0, len(texts), BATCH_LIMIT), start=1):
            batch = texts[start:start + BATCH_LIMIT]
            # slices texts into groups of at most 100, so each API call stays within the limit

            for attempt in range(1, MAX_EMBED_RETRIES + 1):
                try:
                    response = _client.embeddings.create(model=_EMBED_MODEL, input=batch)
                    break
                except openai.RateLimitError:
                    # Gemini free tier rate limit — back off and retry
                    if attempt == MAX_EMBED_RETRIES:
                        raise
                    wait = 15 * attempt
                    print(f"\n  [{_EMBED_MODEL}] rate-limited during embedding, waiting {wait}s (attempt {attempt}/{MAX_EMBED_RETRIES})")
                    time.sleep(wait)

            all_vectors.extend(item.embedding for item in response.data)

            # Stay below the free-tier tokens-per-minute quota. The pause is
            # intentionally conservative because chunk sizes vary by page.
            if batch_num < total_batches:
                time.sleep(20)

            if on_progress:
                on_progress(batch_num, total_batches)

        return all_vectors
