#!/usr/bin/env python3

import argparse
from pathlib import Path
import sys
from extract_manylinux.extract import Arch, Extractor


def main() -> int:
    parser = argparse.ArgumentParser(description="Extracts CPython runtime from a Manylinux image")
    parser.add_argument("--arch", choices=tuple(str(a) for a in Arch), required=True, help="Target architecture")
    parser.add_argument("--prefix", metavar="PATH", type=Path, required=True, help="Path to the exported container image root")
    parser.add_argument("--tag", required=True, help="Python binary tag (ex: cp311-cp311; select from symlinks in $PREFIX/opt/python)")
    parser.add_argument("--output", "-o", required=True, type=Path, help="Path to store the resulting Relocatable CPython Runtime (RCPR)")
    parsed_args = parser.parse_args()

    arch = Arch[parsed_args.arch.upper()]
    destination: Path = parsed_args.output

    if destination.exists():
        raise FileExistsError(f"{destination} exists")

    extractor = Extractor(
        arch=arch,
        prefix=parsed_args.prefix,
        tag=parsed_args.tag,
    )

    extractor.extract(destination)

    return 0


if __name__ == "__main__":
    sys.exit(main())
