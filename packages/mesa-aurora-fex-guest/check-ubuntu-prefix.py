#!/usr/bin/env python3
"""Check the actual staged libraries and manifests before touching a rootfs."""
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

stage = Path(sys.argv[1]).resolve()
prefix = sys.argv[2]
root = stage / prefix.lstrip('/')
for arch, triplet, bits, machine in [('x86_64', 'x86_64-linux-gnu', 64, 62),
                                     ('i686', 'i386-linux-gnu', 32, 3)]:
    lib = root / 'lib' / triplet
    for path in [lib / 'libvulkan_asahi.so', *lib.glob('libgallium-*.so')]:
        header = path.read_bytes()[:20]
        assert header[:4] == b'\x7fELF' and header[4] == {32: 1, 64: 2}[bits], path
        assert header[5] == 1 and struct.unpack_from('<H', header, 18)[0] == machine, path
    assert list(lib.glob('libgallium-*.so')), lib
    for name in ('asahi', 'aurora', 'zink'):
        assert (lib / 'dri' / f'{name}_dri.so').is_file(), (arch, name)
    manifest = root / f'share/vulkan/icd.d/asahi_icd.{arch}.json'
    icd = json.loads(manifest.read_text())['ICD']
    assert icd['library_path'] == f'{prefix}/lib/{triplet}/libvulkan_asahi.so', icd
    assert icd['library_arch'] == str(bits), icd
    print(f'{arch}: ELF{bits}, matching ICD, asahi/aurora/zink DRI aliases')
for path in root.rglob('*.so*'):
    if not path.is_file() or path.is_symlink():
        continue
    dynamic = subprocess.check_output(['readelf', '-d', str(path)], text=True)
    assert not re.search(r'NEEDED.*(libLLVM|libSPIRV-Tools|libsensors|libunwind)', dynamic), path
    versions = subprocess.check_output(['readelf', '--version-info', str(path)], text=True)
    glibc = [tuple(map(int, v.split('.'))) for v in re.findall(r'\bGLIBC_(\d+\.\d+)', versions)]
    assert not glibc or max(glibc) <= (2, 39), path
egl = json.loads((root / 'share/glvnd/egl_vendor.d/50_mesa.json').read_text())
assert egl['ICD']['library_path'] == 'libEGL_mesa.so.0', egl
assert (root / 'bin/with-mesa').is_file()
assert len((root / '.aurora-mesa-commit').read_text().strip()) == 40
print('Ubuntu 24.04 ABI and LLVM-free runtime checks passed')
