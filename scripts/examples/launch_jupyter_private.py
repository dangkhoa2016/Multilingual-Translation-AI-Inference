"""Start local Jupyter with privately prompted API credentials (never save in notebook).

No .env file is read. The HTTPS URL is typed interactively; the Bearer token
is hidden by getpass. Neither value appears in shell command arguments.
The child kernel inherits the environment from the Jupyter server.
"""
import os
import sys
from getpass import getpass
from pathlib import Path
from urllib.parse import urlsplit


def main() -> None:
    if not sys.stdin.isatty():
        raise SystemExit("Open a local interactive terminal; do not pipe credentials to this launcher.")

    gateway_url = input("Your gateway HTTPS root URL: ").strip().rstrip("/")
    parsed = urlsplit(gateway_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise SystemExit("Provide a valid HTTPS gateway root URL (no embedded credentials).")

    token = getpass("Private API Bearer token (input hidden): ").strip()
    if not token:
        raise SystemExit("Bearer token cannot be empty.")

    env = os.environ.copy()
    env["TRANSLATION_GATEWAY_BASE_URL"] = gateway_url
    env["TRANSLATION_API_BEARER_TOKEN"] = token
    notebook = Path(__file__).resolve().parents[2] / "notebooks" / "translation_api_demo.ipynb"
    # Replace the process: never put private values in CLI arguments or logs.
    os.execvpe(sys.executable, [sys.executable, "-m", "jupyter", "lab", str(notebook)], env)


if __name__ == "__main__":
    main()
