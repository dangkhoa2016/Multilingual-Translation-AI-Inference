# Verify your installation

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](independent-validation.vi.md)

Use this guide to check a local installation, connect the notebook to your
own gateway, and verify a self-hosted deployment. Start with the CPU demo;
GPU checks require your own configured resources and incur cloud charges.

## 1. Check the local API workflow

Follow the [quick start](../README.md#quick-start--no-gpu-required) in a fresh
Python 3.12+ virtual environment with `.[demo]` installed, then run:

```bash
python -m pip check
python scripts/examples/local_demo.py
```

Expect **POST 202**, **GET 200**, `status: completed` and
`is_mock_result == true`. This exercises submission, storage and retrieval
using temporary SQLite and mock text. Real translation is checked separately
on your deployed gateway.

## 2. Send a translation from the notebook

Open the [API notebook](../notebooks/translation_api_demo.ipynb) in Jupyter,
Colab or Kaggle. Leave all live flags off and **Run All offline** once.
This initializes `Client helpers`; they need no edits or reruns for normal use.

1. In **Basic Settings**, choose the model, languages and sample text.
2. Load your gateway and Bearer token through private Secrets.
3. In Basic Settings, enable the paid GPU acknowledgement and submitted-job
   polling. For one model, enable `RUN_SINGLE_MODEL_POST` and choose `"single"`.
   For comparison, enable `RUN_MULTI_MODEL_POST`, choose `"multi"` and select
   `MULTI_MODEL_KEYS` (two by default; opt in to additional backends, up to four). Keep the other POST flag off.
   Run **Basic Settings → Load private Secrets → POST translation → GET job**
   for one model, or substitute **POST benchmark** for comparison.
   Do not Run All with paid POST flags enabled.
4. For read-only follow-up, turn both POST flags off and run
   **Basic Settings → GET job**. Enable `SHOW_TRANSLATIONS` only for non-sensitive text.
   Compare the latest attempt of each model in its table column; a failed model
   keeps its status/error while other translations remain readable.

For a new request after checking the previous outcome, change both
`TEXT_TO_TRANSLATE` and `NEW_SINGLE_REQUEST_ACTION`, or `NEW_BENCHMARK_REQUEST_ACTION`
for comparison, in Basic Settings. Preserve the original
key/payload for an uncertain POST and reconcile before submitting again.

## 3. Resume an accepted job after restart

Before restarting, save the accepted UUID privately using **Save accepted job UUID** /
**View saved job UUID** in the notebook. Temporarily set `SHOW_JOB_IDS=True`,
run the read-only UUID cell, save it as private `TRANSLATION_EXISTING_JOB_ID`,
clear outputs and reset `SHOW_JOB_IDS=False`.

After restarting the kernel:

1. **Run All offline** with every live flag off to initialize the new kernel.
2. In Basic Settings keep `RUN_SINGLE_MODEL_POST=False`, `RUN_MULTI_MODEL_POST=False`
   and `RUN_SUBMITTED_JOB_POLL=False`. In **Advanced Settings** set `RUN_EXISTING_JOB_POLL=True`.
3. Restore `TRANSLATION_GATEWAY_BASE_URL`, `TRANSLATION_API_BEARER_TOKEN`
   and `TRANSLATION_EXISTING_JOB_ID` privately. For Colab/Kaggle Secrets, select
   the provider and set `LOAD_EXISTING_JOB_ID_FROM_SECRETS=True`; keep it `False`
   for local environment variables. UUID-only GET does not require a persisted request key.
4. Run **Basic Settings → Advanced Settings → Load private Secrets → GET job**.
   This sequence sends no POST and creates no GPU job. If the UUID or original
   credentials are missing, recover them before proceeding.

## 4. Check your self-hosted deployment

| Component | Check | Expected result |
|---|---|---|
| Database and API | Follow [deployment](deployment.md), apply migrations and use an authenticated mock gateway | Jobs and results persist in your PostgreSQL database |
| Model files | Verify the pinned GGUF files and configure your Modal Secrets/Volumes | All four artifacts match the model manifest |
| GPU inference | Enable the GPU dispatcher and run the opt-in smoke commands in [reliability](reliability.md) | Requested runs complete with nonmock output |
| Recovery | Repeat the GET-only sequence above for an accepted job | The same job can be read without a new POST |

Record the source revision, dependency versions and observed results when
comparing installations. CPU mocks, GPU execution and translation-quality
evaluation check different aspects; see [reliability](reliability.md) and
the [community roadmap](roadmap.md) for operational and integration proposals.

## Share feedback

If a step fails or needs explanation, open a
[GitHub Issue](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/issues)
with your OS, Python/package versions, the step reached, expected behavior
and a minimal reproduction. Remove tokens, private URLs, UUIDs and translation
text from attachments. See [support](../.github/SUPPORT.md) for help.
