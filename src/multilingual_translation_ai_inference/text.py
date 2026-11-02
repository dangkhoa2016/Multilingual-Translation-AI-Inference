"""Storage-safe Unicode text; preserve valid characters without normalization."""


def validate_translation_text(value: str) -> str:
    if "\x00" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError("Text cannot contain NUL or isolated Unicode surrogates")
    return value
