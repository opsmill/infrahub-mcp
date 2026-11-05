#!/usr/bin/env bash
# Exercise the release SBOM commands against a local image without registry credentials.
set -euo pipefail

fixture_dir=$(mktemp -d)
image="infrahub-mcp-sbom-smoke:$(basename "$fixture_dir" | tr '[:upper:]' '[:lower:]')"
cleanup() {
  docker image rm "$image" >/dev/null 2>&1 || true
  rm -rf "$fixture_dir"
}
trap cleanup EXIT

mkdir -p "$fixture_dir/site-packages/infrahub_mcp-1.2.3.dist-info"
cat > "$fixture_dir/site-packages/infrahub_mcp-1.2.3.dist-info/METADATA" <<'METADATA'
Metadata-Version: 2.1
Name: infrahub-mcp
Version: 1.2.3
METADATA
cat > "$fixture_dir/Dockerfile" <<'DOCKERFILE'
FROM scratch
COPY site-packages /usr/local/lib/python3.13/site-packages
DOCKERFILE

docker build --tag "$image" "$fixture_dir"
syft version
syft "docker:$image" --output "spdx-json=$fixture_dir/sbom.spdx.json"
syft "docker:$image" --output "cyclonedx-json=$fixture_dir/sbom.cdx.json"

python3 - "$fixture_dir" <<'PYTHON'
import json
import sys
from pathlib import Path

output = Path(sys.argv[1])
spdx = json.loads((output / "sbom.spdx.json").read_text())
assert spdx["spdxVersion"].startswith("SPDX-2."), spdx["spdxVersion"]
assert any(
    package["name"] == "infrahub-mcp" and package.get("versionInfo") == "1.2.3"
    for package in spdx["packages"]
), "SPDX output did not identify the installed Python package"
cyclonedx = json.loads((output / "sbom.cdx.json").read_text())
assert cyclonedx["bomFormat"] == "CycloneDX", cyclonedx["bomFormat"]
assert any(
    package["name"] == "infrahub-mcp" and package.get("version") == "1.2.3"
    for package in cyclonedx["components"]
), "CycloneDX output did not identify the installed Python package"
print("PASS: image scan identified infrahub-mcp 1.2.3 in SPDX and CycloneDX")
PYTHON
