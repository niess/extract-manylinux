import collections
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import requests
import subprocess
import tempfile
import time
from typing import List, Optional


CHUNK_SIZE = 8189

SUCCESS = 200


class DownloadError(Exception):
    pass

class TarError(Exception):
    pass


@dataclass(frozen=True)
class Downloader:

    '''Manylinux image.'''
    image: str

    '''Authentication token.'''
    token: str = field(init=False)


    def __post_init__(self):
        # Authenticate to quay.io.
        repository = f'pypa/{self.image}'
        url = 'https://quay.io/v2/auth'
        url = f'{url}?service=quay.io&scope=repository:{repository}:pull'
        r = requests.request('GET', url)
        if r.status_code == SUCCESS:
            object.__setattr__(self, 'token', r.json()['token'])
        else:
            raise DownloadError(r.status_code, r.text, r.headers)


    def download(self, destination=None, tag='latest'):
        destination = destination or self.image

        # Fetch manifest.
        repository = f'pypa/{self.image}'
        url = f'https://quay.io/v2/{repository}/manifests/{tag}'
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Accept': 'application/vnd.docker.distribution.manifest.v2+json'
        }
        r = requests.request('GET', url, headers=headers)
        if r.status_code == SUCCESS:
            manifest = r.json()
        else:
            raise DownloadError(r.status_code, r.text, r.headers)

        # Fetch layers using a producer / consumer pattern for extracting
        # tarfiles in parallel (using a subprocess).
        tarfiles = collections.deque()
        workdir = None

        def fetch_layers():
            for layer in manifest['layers']:
                digest = layer['digest']
                hash_ = digest.split(':', 1)[-1]
                filename = f'{hash_}.tar.gz'
                url = f'https://quay.io/v2/{repository}/blobs/{digest}'
                r = requests.request('GET', url, headers=headers, stream=True)
                if r.status_code == SUCCESS:
                    print(f'fetching {filename}')
                else:
                    raise DownloadError(r.status_code, r.text, r.headers)

                hasher = hashlib.sha256()
                with open(workdir / filename, "wb") as f:
                    for chunk in r.iter_content(CHUNK_SIZE): 
                        if chunk:
                            f.write(chunk)
                            hasher.update(chunk)
                            yield

                h = hasher.hexdigest()
                if h != hash_:
                    raise DownloadError(
                        f'bad hash (expected {name}, found {h})'
                    )
                else:
                    tarfiles.append(filename)
                    yield
            else:
                return

        extractor = None
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            for _ in fetch_layers():
                if extractor is None:
                    try:
                        filename = tarfiles.popleft()
                    except IndexError:
                        continue
                    else:
                        extractor = TarExtractor(
                            filename = workdir / filename,
                            destination = destination,
                            clean = True
                        )
                        print(f'extracting {filename}')
                else:
                    if extractor.done():
                        extractor = None
            else:
                if extractor:
                    extractor.extract()

                while tarfiles:
                    filename = tarfiles.popleft()
                    extractor = TarExtractor(
                        filename = filename,
                        destination = destination,
                        clean = True
                    )
                    print(f'extracting {filename}')
                    extractor.extract()


@dataclass(frozen=True)
class TarExtractor:
    '''A tar file extractor running as a suprocess, for parallelisation.'''

    filename: Path
    destination: str
    clean: bool = False

    process: subprocess.Popen = field(init=False)

    def __post_init__(self):
        cmd = ' && '.join((
            f'mkdir -p {self.destination}',
            f'tar -xzf {self.filename} -C {self.destination}',
            f'chmod u+rw -R {self.destination}'
        ))
        process = subprocess.Popen(
            cmd,
            stdout = subprocess.PIPE,
            stderr = subprocess.PIPE,
            shell = True
        )
        object.__setattr__(self, 'process', process)

    def extract(self):
        _, err = self.process.communicate()
        if self.clean:
            self.filename.unlink()
        if err:
            raise TarError(err.decode())

    def done(self) -> bool:
        if self.process.poll() is None:
            return False
        else:
            self.extract()
            return True
