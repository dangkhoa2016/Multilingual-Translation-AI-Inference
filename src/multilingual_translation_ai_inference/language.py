"""Free-form language labels: no hard-coded list of supported languages."""

MAX_LANGUAGE_LABEL_LENGTH = 64


def normalize_language_label(value: str) -> str:
    """Accept any printable language code or name without predicting model support."""
    if not isinstance(value, str):
        raise ValueError("Language must be a string")
    label = value.strip()
    if (not label or len(label) > MAX_LANGUAGE_LABEL_LENGTH
            or not label.isprintable() or not any(char.isalpha() for char in label)):
        raise ValueError("Language must be a printable code or name (1–64 characters)")
    return label


def same_language(source: str, target: str) -> bool:
    """Compare user labels without claiming code/name aliases are equivalent."""
    return source.casefold() == target.casefold()
