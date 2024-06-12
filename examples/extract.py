#! /usr/bin/env python3
from extract_manylinux.extract import Arch, Extractor
from pathlib import Path
from shutil import make_archive

for arch in (Arch.AARCH64, Arch.I686, Arch.X86_64):
    extractor = Extractor(
        arch=arch,
        prefix=Path(f'images/2014/{arch}'),
        tag='cp311-cp311'
    )
    destination = Path(f'extracted/python3.11-2014_{arch}')
    extractor.extract(destination)
    make_archive(str(destination), 'gztar', destination.parent,
                 destination.name)
