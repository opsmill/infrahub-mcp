"""Check that the image distrusts the compromised eMudhra intermediate CAs.

The incident page (https://emudhra.we-have-a-problem.com/#check) serves test
hosts whose certificates chain through the compromised intermediates, both
directly to emSign ECC Root CA - G3 and through the Sectigo cross-signs to
AAA Certificate Services. A patched client rejects every one of them, while a
normal host still verifies.

A rejection counts only when the reason is that the issuer is not trusted or
that the certificate is rejected. A timeout, a DNS failure, an expired test
certificate or a host name mismatch proves nothing, so each of them fails the
check instead of passing it.

The hosts are checked three ways:

- Python's ssl module with the operating system store, as the Infrahub SDK uses it.
- Python's ssl module with the certifi bundle, when certifi is installed.
- curl, which uses OpenSSL and the operating system store directly.

Python 3.13.18 and later also block the compromised keys in the ssl module, so
a Python handshake is rejected when either the interpreter or the trust store
has the fix. To test each store on its own, the check also requires that
neither affected root is loaded into the Python contexts, and curl's handshake
does not go through Python at all.

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
from collections.abc import Callable, Iterable
from typing import Any

COMPROMISED_HOSTS = (
    "dv-g3b-emudhra.we-have-a-problem.com",
    "dv-g3b-aaa-emudhra.we-have-a-problem.com",
    "dv-g3b-noct-emudhra.we-have-a-problem.com",
    "dv-g3b-aaa-noct-emudhra.we-have-a-problem.com",
)
TRUSTED_HOSTS = ("pypi.org",)
# The roots that Debian's ca-certificates 20250419+deb13u1 removes (Debian bug #1151413).
AFFECTED_ROOTS = ("emSign ECC Root CA - G3", "AAA Certificate Services")

# OpenSSL verification errors that mean the chain does not end in a trusted root,
# or that a certificate in it is blocked. Python and curl report the same text.
REJECTION_REASONS = frozenset(
    {
        "unable to get issuer certificate",
        "unable to get local issuer certificate",
        "self-signed certificate in certificate chain",
        "certificate rejected",
    }
)
# curl exit code for a certificate that cannot be verified (CURLE_PEER_FAILED_VERIFICATION).
CURL_VERIFY_FAILED = 60
CURL_REASON_PREFIX = "SSL certificate problem: "

ATTEMPTS = 3
TIMEOUT_SECONDS = 10

VERIFIED = "verified"
REJECTED = "rejected"

# A probe returns VERIFIED, REJECTED or another verification failure, and raises OSError on a network error.
Probe = Callable[[str], str]


def classify_verify_error(reason: str) -> str:
    """Return REJECTED for a distrust reason, or a description of any other verification failure."""
    if reason in REJECTION_REASONS:
        return REJECTED
    return f"verification failed for another reason: {reason}"


def classify_curl(returncode: int, stderr: str) -> str | None:
    """Map a curl result to VERIFIED, REJECTED or another verification failure; None means a network error."""
    if returncode == 0:
        return VERIFIED
    if returncode != CURL_VERIFY_FAILED:
        return None
    for line in stderr.splitlines():
        _, found, reason = line.partition(CURL_REASON_PREFIX)
        if found:
            return classify_verify_error(reason.strip())
    return classify_verify_error(stderr.strip())


def affected_roots_in(ca_certs: Iterable[dict[str, Any]]) -> list[str]:
    """Return the affected roots among CA certificates as `SSLContext.get_ca_certs()` describes them."""
    names = {value for cert in ca_certs for rdn in cert.get("subject", ()) for key, value in rdn if key == "commonName"}
    return [root for root in AFFECTED_ROOTS if root in names]


def with_retries(probe: Probe, host: str) -> str:
    """Return the probe's result, or the last network error after ATTEMPTS tries."""
    error = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return probe(host)
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"
        if attempt < ATTEMPTS:
            time.sleep(2 * attempt)
    return error


def python_probe(context: ssl.SSLContext) -> Probe:
    """Probe a host with a TLS handshake through Python's ssl module."""

    def probe(host: str) -> str:
        try:
            with (
                socket.create_connection((host, 443), timeout=TIMEOUT_SECONDS) as sock,
                context.wrap_socket(sock, server_hostname=host),
            ):
                return VERIFIED
        except ssl.SSLCertVerificationError as exc:
            return classify_verify_error(exc.verify_message)

    return probe


def curl_probe(curl: str) -> Probe:
    """Probe a host with curl."""

    def probe(host: str) -> str:
        command = [curl, "-sS", "-o", "/dev/null", "--max-time", str(TIMEOUT_SECONDS), f"https://{host}/"]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
        result = classify_curl(completed.returncode, completed.stderr)
        if result is None:
            raise OSError(f"curl exit {completed.returncode}: {completed.stderr.strip()}")
        return result

    return probe


def report(name: str, subject: str, result: str, expected: str) -> int:
    ok = result == expected
    print(f"{'ok  ' if ok else 'FAIL'} [{name}] {subject}: {result} (expected {expected})")
    return 0 if ok else 1


def check_store(name: str, context: ssl.SSLContext) -> int:
    """Check that no affected root is loaded into a Python context."""
    ca_certs = context.get_ca_certs()
    if not ca_certs:
        return report(name, "store contents", "no CA certificates loaded from a file", "inspectable")
    found = affected_roots_in(ca_certs)
    return report(name, "affected roots", ", ".join(found) or "absent", "absent")


def check_hosts(name: str, probe: Probe) -> int:
    expectations = [(host, REJECTED) for host in COMPROMISED_HOSTS]
    expectations += [(host, VERIFIED) for host in TRUSTED_HOSTS]
    return sum(report(name, host, with_retries(probe, host), expected) for host, expected in expectations)


def main() -> int:
    contexts = {"python, system store": ssl.create_default_context()}
    try:
        import certifi  # optional: only present when a dependency pulls it in
    except ImportError:
        print("skip [python, certifi]: certifi is not installed")
    else:
        contexts[f"python, certifi {certifi.__version__}"] = ssl.create_default_context(cafile=certifi.where())

    failures = 0
    for name, context in contexts.items():
        failures += check_store(name, context)
        failures += check_hosts(name, python_probe(context))

    curl = shutil.which("curl")
    if curl is None:
        failures += report("curl, system store", "curl", "not installed", "installed")
    else:
        failures += check_hosts("curl, system store", curl_probe(curl))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
