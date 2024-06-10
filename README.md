# Extract CPython runtimes from a Manylinux image

This project is an example illustrating how one could produce a Relocatable
CPython Runtime (RCPR) from a Manylinux Docker image.

> [!TIP]
> The method used herein seems to be cross-plateform. That is, a functional
> `aarch64` RCPR was produced from an `x86_64` system.


## Requirements

- [Patchelf](https://github.com/NixOS/patchelf), which is looked for under
  `extract_manylinux/bin/` (or alternativelly under `$HOME/.local/bin`). Note
  that we used version `0.14.3` during our tests.

- An extracted Manylinux image. For instance, using `docker` one can produce a
  tarball of an aarch64 image, as

  ```bash
  docker export $(docker create quay.io/pypa/manylinux2014_aarch64) \
    --output="2014_aarch64.tar"
  ```

  The tarball should then be extracted to a local folder (`images/2014/aarch64`
  during our tests).


## Usage

The [Extractor](extract_manylinux/extract.py#L50) class let us produce a RCPR
from the extracted Manylinux image (providing a valid tag within the images,
e.g. `cp311-cp311`). See, the [test.py](scripts/test.py) script for an example
of usage.

## Result

Resulting RCPRs are available from the
[releases](https://github.com/niess/extract-manylinux/releases/tag/rolling)
section.
