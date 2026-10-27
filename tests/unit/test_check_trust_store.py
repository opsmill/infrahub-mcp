"""Tests for classifying the results of the eMudhra trust store check."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_trust_store.py"
spec = importlib.util.spec_from_file_location("check_trust_store", SCRIPT)
if spec is None or spec.loader is None:
    msg = f"could not load trust store check script at {SCRIPT}"
    raise ImportError(msg)
check_trust_store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_trust_store)

REJECTED = check_trust_store.REJECTED
VERIFIED = check_trust_store.VERIFIED

CURL_HINT = "More details here: https://curl.se/docs/sslcerts.html\n"


@pytest.mark.parametrize(
    "reason",
    [
        "unable to get local issuer certificate",
        "unable to get issuer certificate",
        "self-signed certificate in certificate chain",
        "certificate rejected",
    ],
)
def test_distrust_reasons_count_as_rejection(reason: str) -> None:
    assert check_trust_store.classify_verify_error(reason) == REJECTED


@pytest.mark.parametrize(
    "reason",
    [
        "certificate has expired",
        "Hostname mismatch, certificate is not valid for 'example.com'.",
        "certificate is not yet valid",
    ],
)
def test_other_verification_failures_do_not_count_as_rejection(reason: str) -> None:
    result = check_trust_store.classify_verify_error(reason)

    assert result != REJECTED
    assert reason in result


def test_curl_success_is_verified() -> None:
    assert check_trust_store.classify_curl(0, "") == VERIFIED


def test_curl_untrusted_issuer_is_rejected() -> None:
    stderr = "curl: (60) SSL certificate problem: unable to get local issuer certificate\n" + CURL_HINT

    assert check_trust_store.classify_curl(60, stderr) == REJECTED


def test_curl_expired_certificate_is_not_rejected() -> None:
    stderr = "curl: (60) SSL certificate problem: certificate has expired\n" + CURL_HINT

    result = check_trust_store.classify_curl(60, stderr)

    assert result != REJECTED
    assert "certificate has expired" in result


def test_curl_hostname_mismatch_is_not_rejected() -> None:
    stderr = "curl: (60) SSL: no alternative certificate subject name matches target hostname 'example.com'\n"

    assert check_trust_store.classify_curl(60, stderr) != REJECTED


@pytest.mark.parametrize("returncode", [6, 7, 28, 35])
def test_curl_network_errors_are_not_a_result(returncode: int) -> None:
    assert check_trust_store.classify_curl(returncode, "curl: error") is None


def _ca(common_name: str) -> dict[str, object]:
    return {"subject": ((("organizationName", "Example"),), (("commonName", common_name),))}


def test_affected_roots_are_found_by_common_name() -> None:
    certs = [_ca("emSign ECC Root CA - C3"), _ca("AAA Certificate Services"), _ca("ISRG Root X1")]

    assert check_trust_store.affected_roots_in(certs) == ["AAA Certificate Services"]


def test_store_without_affected_roots_reports_none() -> None:
    certs = [_ca("emSign ECC Root CA - C3"), _ca("emSign Root CA - G1"), _ca("ISRG Root X1")]

    assert check_trust_store.affected_roots_in(certs) == []


def test_network_errors_are_retried_then_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_trust_store.time, "sleep", lambda _seconds: None)
    calls: list[str] = []

    def probe(host: str) -> str:
        calls.append(host)
        msg = "timed out"
        raise TimeoutError(msg)

    result = check_trust_store.with_retries(probe, "example.com")

    assert len(calls) == check_trust_store.ATTEMPTS
    assert result == "TimeoutError: timed out"
