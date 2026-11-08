"""Layer count and sizes of an image saved by `docker save` (spike only).

Usage: python3 layers.py <image.tar>

Prints one JSON object: the number of layers, their total size uncompressed,
and compressed with gzip level 6, the compression of a registry push. Works
with both Docker image stores: the classic store saves layers uncompressed,
the containerd store saves them as pulled (often already gzip-compressed).
"""

import gzip
import json
import sys
import tarfile
import zlib

CHUNK = 1 << 20


def sizes(stream: object) -> tuple[int, int]:
    """(uncompressed, gzip -6) sizes of a layer, read once."""
    raw = 0
    compressor = zlib.compressobj(6, zlib.DEFLATED, 31)
    compressed = 0
    while chunk := stream.read(CHUNK):  # type: ignore[attr-defined]
        raw += len(chunk)
        compressed += len(compressor.compress(chunk))
    compressed += len(compressor.flush())
    return raw, compressed


def main(path: str) -> int:
    with tarfile.open(path) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))  # type: ignore[arg-type]
        layers = manifest[0]["Layers"]
        total_raw = total_compressed = 0
        for name in layers:
            member = archive.extractfile(name)
            assert member is not None  # noqa: S101 - a layer listed by the manifest
            head = member.read(2)
            member.seek(0)
            if head == b"\x1f\x8b":
                # Already gzip: its size is what a registry stores.
                total_compressed += archive.getmember(name).size
                with gzip.open(member) as layer:
                    total_raw += sizes(layer)[0]
            else:
                raw, compressed = sizes(member)
                total_raw += raw
                total_compressed += compressed
    result = {"layers": len(layers), "uncompressed": total_raw, "compressed": total_compressed}
    sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
