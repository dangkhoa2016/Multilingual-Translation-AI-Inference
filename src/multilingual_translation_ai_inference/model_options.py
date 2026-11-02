"""Bounded per-request sampling overrides for the internal llama.cpp chat endpoint.

Engine resources (context, GPU layers, batch size and parallelism) are not request
parameters: each worker owns one persistent model server. Never expose an
arbitrary llama-server JSON body or CLI switch to an API caller.
"""
import math

from .model_registry import MODEL_REGISTRY

DEFAULT_DECODING: dict[str, dict[str, int | float]] = {
    "hy_mt2_30b": {"temperature": 0.7, "top_p": 1.0, "top_k": -1},
    "index_35b": {"temperature": 0.0, "top_p": 1.0, "top_k": 20},
    "gemma4_31b_it": {"temperature": 1.0, "top_p": 0.95, "top_k": 64},
    "qwen35_35b": {"temperature": 0.7, "top_p": 0.8, "top_k": 20},
}
assert set(DEFAULT_DECODING) == set(MODEL_REGISTRY)

DEFAULT_MAX_TOKENS = 1536
MAX_MAX_TOKENS = 3072  # n_ctx is 4096; leave headroom for translation prompts.

_FLOAT_RANGES = {
    "temperature": (0.0, 2.0),
    "top_p": (0.0, 1.0),
    "min_p": (0.0, 1.0),
    "typical_p": (0.0, 1.0),
    "repeat_penalty": (0.0, 3.0),
    "frequency_penalty": (-2.0, 2.0),
    "presence_penalty": (-2.0, 2.0),
    "dynatemp_range": (0.0, 2.0),
    "dynatemp_exponent": (0.01, 10.0),
    "xtc_probability": (0.0, 1.0),
    "xtc_threshold": (0.0, 1.0),
    "dry_multiplier": (0.0, 10.0),
    "dry_base": (1.0, 5.0),
    "mirostat_tau": (0.0, 20.0),
    "mirostat_eta": (0.0, 1.0),
    "top_n_sigma": (-1.0, 10.0),
}
_INT_RANGES = {
    "top_k": (-1, 1000),
    "max_tokens": (1, MAX_MAX_TOKENS),
    "seed": (-1, 4294967295),
    "repeat_last_n": (-1, 4096),
    "dry_allowed_length": (1, 512),
    "dry_penalty_last_n": (-1, 4096),
    "mirostat": (0, 2),
}
_BOOLEAN_OPTIONS = frozenset({"enable_thinking", "ignore_eos"})
SPECIAL_OPTIONS = frozenset({"stop"})
SUPPORTED_MODEL_OPTIONS = frozenset(_FLOAT_RANGES) | frozenset(_INT_RANGES) | _BOOLEAN_OPTIONS | SPECIAL_OPTIONS


def validate_model_config(config: object) -> dict:
    """Validate without importing FastAPI/Pydantic into the GPU image."""
    if not isinstance(config, dict) or len(config) > len(SUPPORTED_MODEL_OPTIONS):
        raise ValueError("model config must be an object with supported sampling options")
    if not set(config) <= SUPPORTED_MODEL_OPTIONS:
        raise ValueError("Unsupported model sampling option")
    result = {}
    for key, value in config.items():
        if key in _FLOAT_RANGES:
            lo, hi = _FLOAT_RANGES[key]
            # Bound exact integers before any conversion to float: isfinite()
            # converts int to float and overflows on inputs such as 10**400.
            if (type(value) not in (int, float) or not lo <= value <= hi
                    or (type(value) is float and not math.isfinite(value))):
                raise ValueError(f"{key} must be a finite number between {lo} and {hi}")
        elif key in _INT_RANGES:
            lo, hi = _INT_RANGES[key]
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError(f"{key} must be an integer between {lo} and {hi}")
        elif key in _BOOLEAN_OPTIONS:
            if type(value) is not bool:
                raise ValueError(f"{key} must be Boolean")
        elif key == "stop":
            if (not isinstance(value, list) or not 1 <= len(value) <= 8
                    or any(not isinstance(item, str) or not 1 <= len(item) <= 100
                           or "\x00" in item
                           or any(0xD800 <= ord(ch) <= 0xDFFF for ch in item)
                           for item in value)):
                raise ValueError("stop must be a list of 1–8 valid strings of at most 100 characters")
        result[key] = value
    return result


def validate_model_configs(configs: object, selected_models: list[str] | None = None) -> dict[str, dict]:
    if not isinstance(configs, dict) or len(configs) > 4:
        raise ValueError("model_configs must be an object for up to four models")
    if (any(type(key) is not str or key not in MODEL_REGISTRY for key in configs)
            or (selected_models is not None and not set(configs) <= set(selected_models))):
        raise ValueError("model_configs must reference only selected supported models")
    return {key: validate_model_config(value) for key, value in configs.items()}


def effective_decoding(model_key: str, overrides: object) -> dict:
    if model_key not in DEFAULT_DECODING:
        raise ValueError("Unsupported translation model")
    config = validate_model_config(overrides)
    params = {"max_tokens": DEFAULT_MAX_TOKENS, "seed": 42, "stream": False}
    params.update(DEFAULT_DECODING[model_key])
    if "enable_thinking" in config:
        config = dict(config)
        params["chat_template_kwargs"] = {"enable_thinking": config.pop("enable_thinking")}
    params.update(config)
    return params
