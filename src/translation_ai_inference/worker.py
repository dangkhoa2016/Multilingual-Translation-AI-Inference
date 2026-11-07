"""CPU-only fake translation, for orchestration tests (not usable as a translator)."""
from .repository import JobRepository


def process_mock_translation_run(repo: JobRepository, run_id: str, claim_token: str) -> bool:
    claimed = repo.start_run(run_id, claim_token)
    if claimed is None:
        return False
    source, target, text, _options, model = claimed
    # Explicitly labeled; NEVER return misleading fake text as real translation.
    fake_translation = (f"[MOCK ONLY — NOT A TRANSLATION; model={model}; "
                        f"source={source}; target={target}]\n{text}")
    return repo.finish_run(run_id, claim_token, fake_translation, mock=True)
