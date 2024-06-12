from dataclasses import dataclass, field
from enum import auto, Enum
import glob
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
from typing import Dict, List, NamedTuple, Optional, Union


class Arch(Enum):
    '''Supported architectures.'''
    AARCH64 = auto()
    I686 = auto()
    X86_64 = auto()

    def __str__(self):
        return self.name.lower()


class PythonImpl(Enum):
    '''Supported Python implementations.'''
    CPYTHON = auto()


class PythonVersion(NamedTuple):
    major: int
    minor: int
    patch: Union[int, str]

    @classmethod
    def from_str(cls, value: str) -> 'PythonVersion':
        major, minor, patch = value.split('.', 2)
        try:
            patch = int(patch)
        except ValueError:
            pass
        return cls(int(major), int(minor), patch)

    def long(self) -> str:
        return f'{self.major}.{self.minor}.{self.patch}'

    def short(self) -> str:
        return f'{self.major}.{self.minor}'


@dataclass(frozen=True)
class Extractor:
    '''Python extractor from a Manylinux image.'''

    arch: Arch
    '''Target architecture'''

    prefix: Path
    '''Target image path'''

    tag: str
    '''Python binary tag'''


    excludelist: Optional[Path] = None
    '''Exclude list for shared dlibraries.'''

    patchelf: Optional[Path] = None
    '''Patchelf executable.'''


    '''Excluded shared libraries.'''
    excluded: List[str] = field(init=False)

    impl: PythonImpl = field(init=False)
    '''Python implementation'''

    library_path: List[str] = field(init=False)
    '''Search paths for libraries (LD_LIBRARY_PATH)'''

    python_prefix: Path = field(init=False)
    '''Python installation prefix'''

    version: PythonVersion = field(init=False)
    '''Python version'''


    def __post_init__(self):
        # Locate Python installation.
        link = os.readlink(self.prefix / f'opt/python/{self.tag}')
        if not link.startswith('/'):
            raise NotImplementedError()
        object.__setattr__(self, 'python_prefix', self.prefix / link[1:])

        # Parse implementation and version.
        head, tail = Path(link).name.split('-', 1)
        if head == 'cpython':
            impl = PythonImpl.CPYTHON
            version = PythonVersion.from_str(tail)
        else:
            raise NotImplementedError()
        object.__setattr__(self, 'impl', impl)
        object.__setattr__(self, 'version', version)

        # Set libraries search path.
        paths = []
        if self.arch in (Arch.AARCH64, Arch.X86_64):
            paths.append(self.prefix / 'lib64')
        elif self.arch == Arch.I686:
            paths.append(self.prefix / 'lib')
        else:
            raise NotImplementedError()
        paths.append(self.prefix / 'usr/local/lib')

        ssl = glob.glob(str(self.prefix / 'opt/_internal/openssl-*'))
        if ssl:
            paths.append(Path(ssl[0]) / 'lib')

        object.__setattr__(self, 'library_path', paths)

        # Set excluded libraries.
        excludelist = Path(self.excludelist) if self.excludelist \
                      else Path(__file__).parent / 'share/excludelist'
        excluded = []
        with excludelist.open() as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    excluded.append(line)
        object.__setattr__(self, 'excluded', excluded)

        # Set patchelf, if not provided.
        if self.patchelf is None:
            paths = (
                # Rocky linux installs 'patchelf' into /bin
                Path('/bin'),
                Path(__file__).parent / 'bin',
                Path.home() / '.local/bin'
            )
            for path in paths:
                patchelf = path / 'patchelf'
                if patchelf.exists():
                    break
            else:
                raise FileNotFoundError(f"'patchelf' not found in any of: {[str(p) for p in paths]}")
            object.__setattr__(self, 'patchelf', patchelf)
        else:
            assert(self.patchelf.exists())


    def extract(self, destination):
        '''Extract Python runtime.'''

        python = f'python{self.version.short()}'
        runtime = f'bin/{python}'
        packages = f'lib/{python}'

        # Locate include files.
        include = glob.glob(str(self.python_prefix / 'include/*'))
        if include:
            include = Path(include[0]).name
            include = f'include/{include}'
        else:
            raise NotImplementedError()

        # Clone Python installation.
        (destination / 'bin').mkdir(exist_ok=True, parents=True)
        shutil.copy(self.python_prefix / runtime, destination / runtime)
        short = Path(destination / f'bin/python{self.version.major}')
        short.unlink(missing_ok=True)
        short.symlink_to(python)
        short = Path(destination / f'bin/python')
        short.unlink(missing_ok=True)
        short.symlink_to(f'python{self.version.major}')

        for folder in (packages, include):
            # XXX Some files are read-only, which prevents overriding the
            # destination in case that a second copy occurs. A workaround would
            # be to copy the files content but changing their permissions.
            # However, there don't seem to be a function for this use case in
            # shutil (i.e. doing so recusively, for directories).
            shutil.copytree(self.python_prefix / folder, destination / folder,
                            symlinks=True, dirs_exist_ok=True)

        # Map binary dependencies.
        libs = self.ldd(self.python_prefix / f'bin/{python}')
        path = Path(self.python_prefix / f'{packages}/lib-dynload')
        for module in glob.glob(str(path / "*.so")):
            l = self.ldd(module)
            libs.update(l)

        # Copy and patch binary dependencies.
        libdir = destination / 'lib'
        for (name, src) in libs.items():
            dst = libdir / name
            shutil.copy(src, dst, follow_symlinks=True)
            # As stated previously, some libraries are read-only, which prevents
            # overriding the destination directory. Below, we change the
            # permission of destination files to read-write (for the owner).
            mode = dst.stat().st_mode
            if not (mode & stat.S_IWUSR):
                mode = mode | stat.S_IWUSR
                dst.chmod(mode)

            self.set_rpath(dst, '$ORIGIN')

        # Patch RPATHs of binary modules.
        path = Path(destination / f'{packages}/lib-dynload')
        for module in glob.glob(str(path / "*.so")):
            src = Path(module)
            dst = os.path.relpath(libdir, src.parent)
            self.set_rpath(src, f'$ORIGIN/{dst}')

        # Patch RPATHs of Python runtime.
        src = destination / runtime
        dst = os.path.relpath(libdir, src.parent)
        self.set_rpath(src, f'$ORIGIN/{dst}')


    def ldd(self, target: Path) -> Dict[str, Path]:
        '''Cross-platform implementation of ldd, using readelf.'''

        pattern = re.compile(r'[(]NEEDED[)]\s+Shared library:\s+\[([^\]]+)\]')
        dependencies = dict()

        def recurse(target: Path):
            result = subprocess.run(f'readelf -d {target}', shell=True,
                                    check=True, capture_output=True)
            stdout = result.stdout.decode()
            matches = pattern.findall(stdout)

            for match in matches:
                if (match not in dependencies) and (match not in self.excluded):
                    path = self.locate_library(match)
                    dependencies[match] = path
                    subs = recurse(path)

        recurse(target)
        return dependencies


    def locate_library(self, name: str) -> Path:
        '''Locate a library given its qualified name.'''

        for dirname in self.library_path:
            path = dirname / name
            if path.exists():
                return path
        else:
            raise FileNotFoundError(name)


    def set_rpath(self, target, rpath):
        cmd = f'{self.patchelf} --print-rpath {target}'
        result = subprocess.run(cmd, shell=True, check=True,
                                capture_output=True)
        current_rpath = result.stdout.decode().strip()
        if current_rpath != rpath:
            cmd = f"{self.patchelf} --set-rpath '{rpath}' {target}"
            subprocess.run(cmd, shell=True, check=True, capture_output=True)
