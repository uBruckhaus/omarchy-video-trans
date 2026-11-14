"""Private, verified store for the offered Whisper models.

Each model is pinned to one Hugging Face commit, and every file faster-whisper loads is
pinned too: model.bin by its SHA256 (Git LFS), the small files by their Git blob SHA-1.
A download goes into a private temporary folder under DATA/whisper (0700), every file is
checked there, and only then is the folder renamed into place and recorded as verified.
Models load only from that folder, never from the shared Hugging Face cache, and only
regular files owned by this user are accepted.
"""
import hashlib
import os
from pathlib import Path
import shutil
import stat

DATA = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'video-trans'
STORE = DATA / 'whisper'

# model → (repository, download size, pinned commit, {file: expected hash})
MODELS = {
    'tiny': ('Systran/faster-whisper-tiny', '75 MB', 'd90ca5fe260221311c53c58e660288d3deb8d356', {
        'config.json': 'gitsha1:3baa18e2b321a2f489614607852a729fcd516480',
        'model.bin': 'sha256:dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1',
        'tokenizer.json': 'gitsha1:7818adb6de9fa3064d3ff81226fdd675be1f6344',
        'vocabulary.txt': 'gitsha1:c9074644d9d1205686f16d411564729461324b75'}),
    'base': ('Systran/faster-whisper-base', '145 MB', 'ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66', {
        'config.json': 'gitsha1:867cf1a0fece1394e01d55e287ba2f09a577c046',
        'model.bin': 'sha256:d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9',
        'tokenizer.json': 'gitsha1:7818adb6de9fa3064d3ff81226fdd675be1f6344',
        'vocabulary.txt': 'gitsha1:c9074644d9d1205686f16d411564729461324b75'}),
    'small': ('Systran/faster-whisper-small', '480 MB', '536b0662742c02347bc0e980a01041f333bce120', {
        'config.json': 'gitsha1:e5047537059bd8f182d9ca64c470201585015187',
        'model.bin': 'sha256:3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671',
        'tokenizer.json': 'gitsha1:7818adb6de9fa3064d3ff81226fdd675be1f6344',
        'vocabulary.txt': 'gitsha1:c9074644d9d1205686f16d411564729461324b75'}),
    'medium': ('Systran/faster-whisper-medium', '1.5 GB', '08e178d48790749d25932bbc082711ddcfdfbc4f', {
        'config.json': 'gitsha1:242aa06a480a7b5509375c645097e87af5136774',
        'model.bin': 'sha256:9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae',
        'tokenizer.json': 'gitsha1:7818adb6de9fa3064d3ff81226fdd675be1f6344',
        'vocabulary.txt': 'gitsha1:c9074644d9d1205686f16d411564729461324b75'}),
    'large-v3': ('Systran/faster-whisper-large-v3', '3 GB', 'edaa852ec7e145841d8ffdb056a99866b5f0a478', {
        'config.json': 'gitsha1:75336feae814999bae6ccccdecf177639ffc6f9d',
        'model.bin': 'sha256:69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1',
        'preprocessor_config.json': 'gitsha1:931c77a740890c46365c7ae0c9d350ba3cca908f',
        'tokenizer.json': 'gitsha1:3a5e2ba63acdcac9a19ba56cf9bd27f185bfff61',
        'vocabulary.json': 'gitsha1:0adcd01e7c237205d593b707e66dd5d7bc785d2d'}),
    # Hugging Face redirects this name to dropbox-dash/…; the commit is the same.
    'turbo': ('mobiuslabsgmbh/faster-whisper-large-v3-turbo', '1.6 GB', '0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf', {
        'config.json': 'gitsha1:0351d1d6870005e865747b781b5d7c23ea0459cd',
        'model.bin': 'sha256:e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da',
        'preprocessor_config.json': 'gitsha1:931c77a740890c46365c7ae0c9d350ba3cca908f',
        'tokenizer.json': 'gitsha1:17456db595adc78a973f97d69d8cb50bc87c0b1c',
        'vocabulary.json': 'gitsha1:0adcd01e7c237205d593b707e66dd5d7bc785d2d'}),
}
MARKER = '.verified'


def folder(model):
    return STORE / f'{model}-{MODELS[model][2]}'


def private_store():
    """DATA/whisper as a real directory owned by this user with mode 0700."""
    STORE.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = os.lstat(STORE)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError('Refusing a Whisper model folder that is not a private directory.')
    os.chmod(STORE, 0o700)
    return STORE


def file_matches(path, expected):
    """A regular file owned by this user (no symlink) whose content has the expected hash."""
    kind, _, value = expected.partition(':')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            return False
        digest = hashlib.sha256() if kind == 'sha256' else hashlib.sha1(b'blob %d\0' % info.st_size)
        while True:
            block = os.read(fd, 1 << 20)
            if not block:
                break
            digest.update(block)
        return digest.hexdigest() == value
    finally:
        os.close(fd)


def adopt(model, download):
    """Checks every file of a finished download and moves it into the store. False (and
    the download deleted) when any file is missing or differs."""
    files = MODELS[model][3]
    try:
        ok = all(file_matches(Path(download) / name, expected) for name, expected in files.items())
    except OSError:
        ok = False
    if not ok:
        shutil.rmtree(download, ignore_errors=True)
        return False
    target = folder(model)
    shutil.rmtree(target, ignore_errors=True)
    os.rename(download, target)
    (target / MARKER).write_text(MODELS[model][2] + '\n')
    return True


def verified(model):
    """True when the pinned model is in the store, recorded, and made of regular files
    owned by this user (their content was checked when they were stored)."""
    if model not in MODELS:
        return False
    target = folder(model)
    try:
        if (target / MARKER).read_text().strip() != MODELS[model][2]:
            return False
        for name in MODELS[model][3]:
            info = os.lstat(target / name)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                return False
        info = os.lstat(STORE)
        return stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077
    except OSError:
        return False
