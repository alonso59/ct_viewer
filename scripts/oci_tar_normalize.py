#!/usr/bin/env python3
"""Rewrite a `docker save` tar so udocker 1.3 can `load` it (called by `./rw update`). Stdlib only.

Docker with the containerd image store saves an OCI layout whose `index.json` udocker's OCI loader
does not follow: a nested index (BuildKit provenance attestations) or Docker v2 manifest media
types inside it. This keeps every blob and writes a flat `index.json` that lists only the image
manifests (attestation manifests dropped) with the OCI manifest media type; the manifest and layer
blobs are unchanged, so digests stay valid.

    python3 scripts/oci_tar_normalize.py IN.tar OUT.tar   # exit 0: OUT written; 3: IN already fine
"""

from __future__ import annotations

import io
import json
import sys
import tarfile
from typing import Any

OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
MANIFESTS = {OCI_MANIFEST, "application/vnd.docker.distribution.manifest.v2+json"}
INDEXES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}


def blob(tar: tarfile.TarFile, digest: str) -> Any:
    member = tar.extractfile("blobs/" + digest.replace(":", "/", 1))
    assert member is not None, digest
    return json.load(member)


def flatten(
    tar: tarfile.TarFile, entries: list[dict[str, Any]], inherited: dict[str, str]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in entries:
        notes = {**inherited, **entry.get("annotations", {})}
        media = entry.get("mediaType", "")
        if media in INDEXES:
            out += flatten(tar, blob(tar, entry["digest"])["manifests"], notes)
        elif media in MANIFESTS:
            attestation = entry.get("platform", {}).get("os") == "unknown"
            if attestation or "vnd.docker.reference.type" in notes:
                continue
            out.append({**entry, "mediaType": OCI_MANIFEST, "annotations": notes})
    return out


def main(src: str, dst: str) -> int:
    with tarfile.open(src) as tar:
        names = set(tar.getnames())
        if "oci-layout" not in names or "index.json" not in names:
            return 3  # classic docker save format: udocker loads it as is
        index = json.load(tar.extractfile("index.json"))  # type: ignore[arg-type]
        if all(m.get("mediaType") == OCI_MANIFEST for m in index["manifests"]):
            return 3
        manifests = flatten(tar, index["manifests"], {})
        if not manifests:
            print("oci_tar_normalize: no image manifest in " + src, file=sys.stderr)
            return 1
        data = json.dumps({**index, "manifests": manifests}).encode()
        with tarfile.open(dst, "w") as out:
            for member in tar:
                if member.name == "index.json":
                    continue
                out.addfile(member, tar.extractfile(member) if member.isfile() else None)
            info = tarfile.TarInfo("index.json")
            info.size = len(data)
            out.addfile(info, io.BytesIO(data))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
