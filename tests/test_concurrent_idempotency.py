"""SQLite stress test for same-key requests; PostgreSQL concurrency is still a P2 gate."""
from concurrent.futures import ThreadPoolExecutor


def test_concurrent_submits_with_same_key_reuse_one_job(client_factory):
    _client, repo = client_factory(dispatcher_mode="record-only")
    payload = {"source_language": "en", "target_language": "vi",
               "text": "The same sentence", "options": {"preserve_formatting": True}}

    def create(_):
        return repo.submit(owner="single-tenant-api", idempotency_key="shared-key",
                           kind="translation", payload=payload, model_keys=["hy_mt2_30b"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(create, range(8)))

    assert len(set(result)) == 1
