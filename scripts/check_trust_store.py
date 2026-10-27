"""Check that the image distrusts the compromised eMudhra intermediate CAs.

The incident page (https://emudhra.we-have-a-problem.com/#check) serves test
hosts whose certificates chain through the compromised intermediates, both
directly to emSign ECC Root CA - G3 and through the Sectigo cross-signs to
AAA Certificate Services. A patched client rejects every one of them, while a
normal host still verifies. Only a certificate verification error counts as a
rejection: a timeout or a DNS failure proves nothing.

The hosts are checked three ways:

- Python's ssl module with the operating system store, as the Infrahub SDK uses it.
- Python's ssl module with the certifi bundle, when certifi is installed.
- curl, which uses OpenSSL and the operating system store directly.

Python 3.13.18 and later also block the compromised keys in the ssl module, so
the Python checks pass when either the interpreter or the trust store has the
fix. The curl check passes only when the operating system store has it.

Run it with the image's own interpreter:

    docker run --rm -i --entrypoint python IMAGE - < scripts/check_trust_store.py
"""

# ruff: noqa: INP001

from __future__ import annotations

import shutil
import socket
import ssl
import subprocess  # noqa: S404
import sys
import time
from collections.abc import Callable

COMPROMISED_HOSTS = (
    "dv-g3b-emudhra.we-have-a-problem.com",
    "dv-g3b-aaa-emudhra.we-have-a-problem.com",
    "dv-g3b-noct-emudhra.we-have-a-problem.com",
    "dv-g3b-aaa-noct-emudhra.we-have-a-problem.com",
)
TRUSTED_HOSTS = ("pypi.org",)

ATTEMPTS = 3
TIMEOUT_SECONDS = 10
# curl exit code for a certificate that cannot be verified (CURLE_PEER_FAILED_VERIFICATION).
CURL_VERIFY_FAILED = 60

VERIFIED = "verified"
REJECTED = "rejected"

Probe = Callable[[str], str | None]


def with_retries(probe: Probe, host: str) -> str:
    """Return VERIFIED or REJECTED, or the last network error after ATTEMPTS tries."""
    error = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            result = probe(host)
        except OSError as exc:
            result, error = None, f"{type(exc).__name__}: {exc}"
        if result is not None:
            return result
        if attempt < ATTEMPTS:
            time.sleep(2 * attempt)
    return error


def python_probe(context: ssl.SSLContext) -> Probe:
    def probe(host: str) -> str | None:
        try:
            with (
                socket.create_connection((host, 443), timeout=TIMEOUT_SECONDS) as sock,
                context.wrap_socket(sock, server_hostname=host),
            ):
                return VERIFIED
        except ssl.SSLCertVerificationError:
            return REJECTED

    return probe


def curl_probe(curl: str) -> Probe:
    def probe(host: str) -> str | None:
        command = [curl, "-sS", "-o", "/dev/null", "--max-time", str(TIMEOUT_SECONDS), f"https://{host}/"]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
        if completed.returncode == 0:
            return VERIFIED
        if completed.returncode == CURL_VERIFY_FAILED:
            return REJECTED
        raise OSError(f"curl exit {completed.returncode}: {completed.stderr.strip()}")

    return probe


def probes() -> dict[str, Probe]:
    found = {"python, system store": python_probe(ssl.create_default_context())}
    try:
        import certifi  # optional: only present when a dependency pulls it in
    except ImportError:
        print("skip [python, certifi]: certifi is not installed")
    else:
        context = ssl.create_default_context(cafile=certifi.where())
        found[f"python, certifi {certifi.__version__}"] = python_probe(context)
    curl = shutil.which("curl")
    if curl is None:
        print("skip [curl, system store]: curl is not installed")
    else:
        found["curl, system store"] = curl_probe(curl)
    return found


def main() -> int:
    failures = 0
    for name, probe in probes().items():
        expectations = [(host, REJECTED) for host in COMPROMISED_HOSTS]
        expectations += [(host, VERIFIED) for host in TRUSTED_HOSTS]
        for host, expected in expectations:
            result = with_retries(probe, host)
            ok = result == expected
            failures += not ok
            print(f"{'ok  ' if ok else 'FAIL'} [{name}] {host}: {result} (expected {expected})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
