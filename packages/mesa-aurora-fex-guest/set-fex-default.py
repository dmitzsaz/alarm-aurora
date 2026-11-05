#!/usr/bin/env python3
"""Select an installed Ubuntu Mesa prefix in FEX's guest environment only.

FEX stores string lists as repeated JSON keys, not JSON arrays. Preserve all
object pairs, including unrelated repeated settings, when editing its files.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import tempfile


class Object(list):
    def get(self, name, default=None):
        return next((v for k, v in self if k == name), default)

    def put(self, name, value):
        self[:] = [(k, v) for k, v in self if k != name] + [(name, value)]


def encode(value, depth=0):
    if isinstance(value, Object):
        pad = '  ' * (depth + 1)
        return '{\n' + ',\n'.join(pad + json.dumps(k) + ': ' + encode(v, depth + 1)
                                   for k, v in value) + '\n' + '  ' * depth + '}'
    if isinstance(value, list):
        return '[' + ', '.join(encode(v, depth + 1) for v in value) + ']'
    return json.dumps(value, ensure_ascii=True)


def load(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'Expected a regular, non-symlink config: {path}')
    data = json.loads(path.read_text(), object_pairs_hook=Object)
    if not isinstance(data, Object):
        raise ValueError(f'Expected a JSON object: {path}')
    return data


def environment(prefix):
    lib = [f'{prefix}/lib/{a}' for a in ('x86_64-linux-gnu', 'i386-linux-gnu')]
    icds = ':'.join(f'{prefix}/share/vulkan/icd.d/asahi_icd.{a}.json'
                    for a in ('x86_64', 'i686'))
    return {
        'LD_LIBRARY_PATH': ':'.join(lib),
        'LIBGL_DRIVERS_PATH': ':'.join(p + '/dri' for p in lib),
        'GBM_BACKENDS_PATH': ':'.join(p + '/gbm' for p in lib),
        'VK_DRIVER_FILES': icds,
        'VK_ICD_FILENAMES': icds,
        '__EGL_VENDOR_LIBRARY_FILENAMES': f'{prefix}/share/glvnd/egl_vendor.d/50_mesa.json',
        '__GLX_VENDOR_LIBRARY_NAME': 'mesa',
        'MESA_LOADER_DRIVER_OVERRIDE': 'zink',
        'ASAHI_M5_BRINGUP': '1',
    }


def validate(rootfs, prefix):
    if not re.fullmatch(r'/opt/aurora-fex-mesa/[a-zA-Z0-9._-]+', prefix):
        raise ValueError('Expected /opt/aurora-fex-mesa/VERSION')
    layer = rootfs / prefix.lstrip('/')
    if not re.fullmatch(r'[0-9a-f]{40}', (layer / '.aurora-mesa-commit').read_text().strip()):
        raise ValueError('Missing source commit marker')
    for arch, triplet, cls, machine in [('x86_64', 'x86_64-linux-gnu', 2, 62),
                                        ('i686', 'i386-linux-gnu', 1, 3)]:
        for name in ('libvulkan_asahi.so', 'libGLX_mesa.so.0', 'libEGL_mesa.so.0',
                     'libgbm.so.1', 'dri/zink_dri.so', 'gbm/dri_gbm.so'):
            path = layer / 'lib' / triplet / name
            if not path.resolve().is_relative_to(layer.resolve()):
                raise ValueError(f'Library escapes the prefix: {path}')
            with path.open('rb') as f:
                header = f.read(20)
            if (header[:6] != b'\x7fELF' + bytes([cls, 1]) or
                    int.from_bytes(header[18:20], 'little') != machine):
                raise ValueError(f'Wrong ELF architecture: {path}')
        icd = json.loads((layer / f'share/vulkan/icd.d/asahi_icd.{arch}.json').read_text())['ICD']
        if (icd['library_arch'] != str(32 if cls == 1 else 64) or
                icd['library_path'] != f'{prefix}/lib/{triplet}/libvulkan_asahi.so'):
            raise ValueError(f'Incorrect ICD: {arch}')
    egl = json.loads((layer / 'share/glvnd/egl_vendor.d/50_mesa.json').read_text())
    if egl['ICD']['library_path'] != 'libEGL_mesa.so.0':
        raise ValueError('Unexpected EGL vendor library')


def atomic_write(path, content, metadata):
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
            os.fchmod(f.fileno(), stat.S_IMODE(metadata.st_mode))
            if os.geteuid() == 0:
                os.fchown(f.fileno(), metadata.st_uid, metadata.st_gid)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def enable(config, rootfs, prefix):
    rootfs = rootfs.resolve()
    validate(rootfs, prefix)
    main = load(config)
    settings = main.get('Config')
    if not isinstance(settings, Object) or Path(settings.get('RootFS', '')).resolve() != rootfs:
        raise ValueError('Config.RootFS does not match the supplied rootfs')
    env = environment(prefix)
    # Include existing AppConfig overrides: their Env list can mask global Env.
    files = [(config, main, settings)]
    for path in sorted((config.parent / 'AppConfig').glob('*.json')):
        doc = load(path)
        app = doc.get('Config')
        files.append((path, doc, app))
    changes = []
    for path, doc, section in files:
        before = path.read_bytes()
        overrides = doc.get('AppOverrides', Object())
        if not isinstance(overrides, Object):
            raise ValueError(f'Expected AppOverrides object: {path}')
        for section in [section, *(v for _, v in overrides)]:
            if section is None:
                continue
            if not isinstance(section, Object):
                raise ValueError(f'Expected Config object: {path}')
            # Keep arbitrary existing Env entries; replace only graphics settings.
            entries = [(k, v) for k, v in section if k == 'Env']
            if any(not isinstance(v, str) or '=' not in v for _, v in entries):
                raise ValueError(f'Env must use repeated string keys, not arrays: {path}')
            if section is settings or entries:
                section[:] = [(k, v) for k, v in section
                              if k != 'Env' or v.split('=', 1)[0] not in env]
                section.extend(('Env', k + '=' + v) for k, v in env.items())
        thunks = doc.get('ThunksDB')
        if path == config and thunks is None:
            thunks = Object()
            doc.put('ThunksDB', thunks)
        if thunks is not None:
            if not isinstance(thunks, Object):
                raise ValueError(f'Expected ThunksDB object: {path}')
            for key in ('GL', 'Vulkan'):
                if path == config or thunks.get(key) is not None:
                    thunks.put(key, 0)
        after = (encode(doc) + '\n').encode()
        if after != before:
            changes.append((path, before, after, path.stat()))
    if not changes:
        print('Already selected; no files changed.')
        return
    backup = Path(tempfile.mkdtemp(prefix='mesa-default-backup.', dir=config.parent))
    records = []
    # Back up every changed file before the first mutation.
    for i, (path, before, after, metadata) in enumerate(changes):
        saved = backup / f'{i}.original'
        shutil.copy2(path, saved)
        if saved.read_bytes() != before:
            raise ValueError(f'Config changed while preparing backup: {path}')
        records.append({'path': str(path), 'backup': saved.name,
                        'sha256': hashlib.sha256(after).hexdigest(),
                        'uid': metadata.st_uid, 'gid': metadata.st_gid})
    (backup / 'manifest.json').write_text(json.dumps(records, indent=2) + '\n')
    # Reject concurrent config edits instead of overwriting them.
    for path, before, _, _ in changes:
        if path.read_bytes() != before:
            raise ValueError(f'Config changed before activation: {path}')
    try:
        for path, _, after, metadata in changes:
            atomic_write(path, after, metadata)
    except BaseException:
        for path, before, _, metadata in changes:
            atomic_write(path, before, metadata)
        raise
    print('Selected for all FEX guests; GL/Vulkan thunks disabled.')
    print(f'Backup: {backup}')
    print('Rollback: ' + shlex.join(['python3', str(Path(__file__).resolve()), 'rollback', str(backup)]))


def rollback(backup):
    records = json.loads((backup / 'manifest.json').read_text())
    # Check all files first; never discard a subsequent user edit.
    for r in records:
        path = Path(r['path'])
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != r['sha256']:
            raise ValueError(f'Config changed since activation; inspect backup before restoring: {path}')
    for r in records:
        path = Path(r['path'])
        saved = backup / r['backup']
        metadata = saved.stat()
        atomic_write(path, saved.read_bytes(), metadata)
        if os.geteuid() == 0:
            os.chown(path, r['uid'], r['gid'])
        os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    print('Original FEX configuration restored; the Mesa payload and backup are retained.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    select = commands.add_parser('enable')
    select.add_argument('config', type=Path)
    select.add_argument('rootfs', type=Path)
    select.add_argument('prefix')
    restore = commands.add_parser('rollback')
    restore.add_argument('backup', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'enable':
            enable(args.config.absolute(), args.rootfs.resolve(), args.prefix)
        else:
            rollback(args.backup.resolve())
    except (ValueError, OSError, KeyError) as e:
        parser.exit(1, f'{e}\n')


if __name__ == '__main__':
    main()
