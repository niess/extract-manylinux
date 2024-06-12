#! /usr/bin/env python3
from extract_manylinux.download import Downloader
from extract_manylinux.extract import Arch
from pathlib import Path


for arch in (Arch.AARCH64, Arch.I686, Arch.X86_64):
    dowloader = Downloader(
        image = f"manylinux2014_{arch}"
    )
    destination = Path(f'images/2014/{arch}')
    dowloader.download(destination)
