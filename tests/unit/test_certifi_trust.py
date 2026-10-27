"""Guard against restoring the compromised emSign trust anchor."""

import ssl

import certifi


def test_certifi_excludes_compromised_emsign_root() -> None:
    """GHSA-6q48-6c7w-9gw2: compromised intermediates chain to ECC G3."""
    context = ssl.create_default_context(cafile=certifi.where())
    certificates = context.get_ca_certs()
    assert certificates, "The certifi trust store must contain usable CA certificates"
    common_names = {
        value
        for certificate in certificates
        for relative_name in certificate["subject"]
        for key, value in relative_name
        if key == "commonName"
    }
    assert "emSign ECC Root CA - G3" not in common_names
