# Reliability and integration checks

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](reliability.vi.md)

Use this guide to understand request handling, inspect recorded integration
results and run the same checks on your own deployment.

## API behavior

- Text accepts up to 1,000 Unicode code points. Language labels are free-form;
  the [model catalog](models.md#supported-input-contract) explains validation and model support.
- Repeating a retained idempotency key with the same payload returns the same
  job; changing the payload returns HTTP 409.
- Authenticated GET polling retrieves durable results. Check the latest attempt
  for each model; uncertain executions require reconciliation before another POST.
- Each model worker handles one inference stream per container. Concurrent API
  requests can queue for the same model.

See the [API reference](development.md#api-contract) for response schemas and states.

## Recorded integration results

These project-recorded summaries describe specific runs. Use the reproduction
steps below to check your own installation with its current code and configuration.

| Scenario | Observed result | Evidence |
|---|---|---|
| Four deployed model loads | All four loaded | [Readiness report](../reports/deployed_gpu_readiness.json) |
| Single-model HTTP job | Completed with nonmock output | [Translation report](../reports/gpu_api_translation.json) |
| Four-model HTTP job | 4/4 completed and persisted | [Benchmark report](../reports/gpu_api_four_model_benchmark.json) |
| Exactly 1,000 Unicode code points to four models | 4/4 completed, nonmock | [Boundary report](../reports/unicode_input_boundary.json) |
| 1,001 characters and invalid language/blank inputs | HTTP 422, no accepted run | [Boundary report](../reports/unicode_input_boundary.json) |
| Same idempotency key and payload | Job reused, no duplicate reservation | [Boundary report](../reports/unicode_input_boundary.json) |
| Same key, different payload | HTTP 409 conflict | [Boundary report](../reports/unicode_input_boundary.json) |
| Two near-simultaneous submissions to Hy-MT2 | Two distinct completed jobs | [Concurrent report](../reports/concurrent_model_jobs.json) |
| Two immediate Hy-MT2 readiness calls | Same GPU UUID; warm reuse observed | [Container report](../reports/gpu_container_reuse.json) |
| Four independently active models | Four distinct L40S GPU UUIDs | [Parallel inference](../reports/four_gpu_parallel_inference.json) |

Language rejections in the archived boundary report reflect the previous
five-code validation policy; current versions allow user-selected language
labels without a whitelist. The archived report retains the policy used for that run.

The 1,000-character test contained non-ASCII text and measured more than
1,000 UTF-8 bytes: character limits refer to **Unicode code points**.

Two immediate readiness calls measured **25.104 s** and **0.459 s**
end-to-end RPC durations. The first call was not guaranteed cold;
neither measurement is an SLA. Two concurrent API submissions
to **the same model** do not imply parallel execution on one GPU,
because that class is limited to one container.

## Evidence provenance and limitations

The linked JSON files are sanitized summaries of past project runs. They cover
infrastructure behavior; they do not measure translation quality or establish
current service availability. Raw execution logs and independent certification
are outside their scope.

| Evidence group | What can be checked | What is not established |
|---|---|---|
| [GPU reservations](../reports/four_gpu_capacity.json) | Four GPU identities and recorded Unix start/end intervals | Model loading or translation quality |
| [GGUF/CUDA inference](../reports/four_gpu_parallel_inference.json) | Four model outputs, memory samples and recorded Unix execution intervals | Production HTTP availability or semantic accuracy |
| [Deployed readiness](../reports/deployed_gpu_readiness.json) | Model-loading status and sampled device memory | Ongoing worker health or guaranteed warm starts |
| [Authenticated HTTP and persistence](../reports/gpu_api_four_model_benchmark.json) | Job completion and nonmock output; see also [PostgreSQL records](../reports/postgresql_gpu_jobs.json) | Independently verifiable execution clock time or a quality score |
| [Boundary and concurrency](../reports/unicode_input_boundary.json) | Input rejection, idempotency and completed jobs; see [concurrent submissions](../reports/concurrent_model_jobs.json) | General performance guarantees |
| [Operations snapshot](../reports/operations_safety_snapshot.json) | Sanitized state counts and alert summary | Cloud billing totals or a continuous monitoring history |

Some GPU reports preserve Unix execution intervals, while other summaries
do **not** contain an independently verifiable capture time. Git commit
metadata identifies when a report entered source control, **not necessarily
when the test ran**. Missing event times cannot be reconstructed from these
summaries. Execution durations are individual
observations, not service-level guarantees. No linked report is a BLEU,
COMET or human translation-quality evaluation.

## Automated validation

The CPU-only test suite normally uses isolated SQLite databases to check
API validation, authentication, idempotency, concurrency controls and
persisted job state. It does **not** exercise production PostgreSQL.
Check your own PostgreSQL and GPU setup using the
[installation verification guide](independent-validation.md).

Focused publication-safety tests reject saved notebook outputs, inline credentials,
accidental live-by-default settings and private identifiers in reports.

## Run the checks

```bash
# Does not allocate GPUs:
python -m pytest -q
python -m ruff check .
PYTHONPATH=src python scripts/api/reliability_smoke.py

# Billable, opt-in real API checks:
set -a; source .env; set +a
export TRANSLATION_GATEWAY_BASE_URL="https://YOUR_GATEWAY.modal.run"
PYTHONPATH=src python scripts/api/reliability_smoke.py --run-boundary
PYTHONPATH=src python scripts/api/reliability_smoke.py --run-concurrency
PYTHONPATH=src python scripts/api/container_reuse.py --run
```

New probe summaries are written to **unique private temporary directories outside
this repository** (directory mode `0700`, file mode `0600`). The scripts print
that path and never overwrite the historical JSON files linked above. Runtime
summaries omit job IDs and raw GPU UUIDs; container reuse is recorded as an
equality result. Review and sanitize a copy before sharing it or adding it to Git.

Current negative tests use a **malformed label** such as `123`, which has no
letter. An arbitrary printable name such as `xx` is accepted by the input
contract and must not be used as an expected HTTP 422 case. Acceptance still
does not establish model support or translation quality.

## Further reading

See [operations](operations.md), [deployment](deployment.md)
and [model details](models.md).
