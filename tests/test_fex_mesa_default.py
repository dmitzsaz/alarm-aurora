"""Exercise reversible FEX selection, including FEX's repeated-key JSON format."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'packages/mesa-aurora-fex-guest/set-fex-default.py'
spec = importlib.util.spec_from_file_location('fex_default', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FexMesaDefaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.rootfs = self.base / 'rootfs'
        self.prefix = '/opt/aurora-fex-mesa/test'
        layer = self.rootfs / self.prefix.lstrip('/')
        layer.mkdir(parents=True)
        (layer / '.aurora-mesa-commit').write_text('d' * 40)
        for arch, triplet, cls, machine in [('x86_64', 'x86_64-linux-gnu', 2, 62),
                                            ('i686', 'i386-linux-gnu', 1, 3)]:
            for name in ('libvulkan_asahi.so', 'libGLX_mesa.so.0', 'libEGL_mesa.so.0',
                         'libgbm.so.1', 'dri/zink_dri.so', 'gbm/dri_gbm.so'):
                path = layer / 'lib' / triplet / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'\x7fELF' + bytes([cls, 1]) + bytes(12) + bytes([machine, 0]))
            manifest = layer / f'share/vulkan/icd.d/asahi_icd.{arch}.json'
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps({'ICD': {'library_arch': str(32 if cls == 1 else 64),
                'library_path': f'{self.prefix}/lib/{triplet}/libvulkan_asahi.so'}}))
        egl = layer / 'share/glvnd/egl_vendor.d/50_mesa.json'
        egl.parent.mkdir(parents=True)
        egl.write_text('{"ICD":{"library_path":"libEGL_mesa.so.0"}}')
        (self.rootfs / 'etc/ld.so.conf.d').mkdir(parents=True)
        (self.rootfs / 'etc/ld.so.cache').write_bytes(b'original-cache')
        icd = self.rootfs / 'usr/share/vulkan/icd.d/asahi_icd.json'
        icd.parent.mkdir(parents=True)
        icd.write_text('{"ICD":{"library_path":"libvulkan_asahi.so"}}')
        self.cache_mock = patch.object(module, 'guest_cache', return_value=b'selected-cache').start()
        self.addCleanup(patch.stopall)
        cache_listing = '\n'.join(f'=> {self.prefix}/lib/{a}/libvulkan_asahi.so'
                                  for a in ('x86_64-linux-gnu', 'i386-linux-gnu'))
        patch.object(module.subprocess, 'run', return_value=type('Result', (), {'stdout': cache_listing})()).start()
        self.config = self.base / 'Config.json'
        self.config.write_text('{"Config":{"RootFS":' + json.dumps(str(self.rootfs)) +
            ',"Env":"KEEP=a","Env":"KEEP_TOO=b","HostEnv":"A=1","HostEnv":"B=2"}}\n')
        self.config.chmod(0o640)
        self.app = self.base / 'AppConfig/WinBox.json'
        self.app.parent.mkdir()
        self.app.write_text('{"ThunksDB":{"GL":1,"Vulkan":1,"asound":1}}\n')

    def enable(self):
        module.enable(self.config, self.rootfs, self.prefix)
        return next(self.base.glob('mesa-default-backup.*'))

    def test_thunks_and_user_environment_survive_activation_and_exact_rollback(self):
        self.config.write_text(self.config.read_text().rstrip()[:-1] +
                               ',"ThunksDB":{"GL":1,"Vulkan":1}}')
        before = {p: p.read_bytes() for p in (self.config, self.app, self.rootfs / 'etc/ld.so.cache')}
        backup = self.enable()
        settings = module.load(self.config).get('Config')
        env = [v for k, v in settings if k == 'Env']
        self.assertIn('KEEP=a', env)
        self.assertIn('KEEP_TOO=b', env)
        self.assertIn('VK_LOADER_DRIVERS_SELECT=asahi*', env)
        self.assertFalse(any('/opt/' in v for v in env))
        self.assertEqual([v for k, v in settings if k == 'HostEnv'], ['A=1', 'B=2'])
        self.assertEqual(json.loads(self.config.read_text())['ThunksDB'], {'GL': 1, 'Vulkan': 1})
        self.assertEqual(self.app.read_bytes(), before[self.app])
        self.enable()
        self.assertEqual(len(list(self.base.glob('mesa-default-backup.*'))), 1)
        module.rollback(backup)
        for p, data in before.items():
            self.assertEqual(p.read_bytes(), data)
        self.assertFalse((self.rootfs / 'etc/ld.so.conf.d/00-aurora-fex-mesa.conf').exists())
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)

    def test_rollback_preflights_new_files_before_restoring_any(self):
        backup = self.enable()
        enabled = self.config.read_bytes()
        conf = self.rootfs / 'etc/ld.so.conf.d/00-aurora-fex-mesa.conf'
        conf.write_text('user edit')
        with self.assertRaisesRegex(ValueError, 'changed since activation'):
            module.rollback(backup)
        self.assertEqual(self.config.read_bytes(), enabled)
        self.assertEqual(conf.read_text(), 'user edit')

    def test_apt_cache_change_refuses_rollback_without_deleting_conf(self):
        backup = self.enable()
        conf = self.rootfs / 'etc/ld.so.conf.d/00-aurora-fex-mesa.conf'
        (self.rootfs / 'etc/ld.so.cache').write_bytes(b'apt-rebuilt-cache')
        with self.assertRaisesRegex(ValueError, 'changed since activation'):
            module.rollback(backup)
        self.assertTrue(conf.exists())

    def test_explicit_app_and_pattern_settings_are_never_edited(self):
        self.app.write_text('{"Config":{"Env":"APP=1","Env":"VK_DRIVER_FILES=/custom.json"},'
                            '"AppOverrides":{"game*":{"Env":"OTHER=1"}},"ThunksDB":{"Vulkan":1}}')
        before = self.app.read_bytes()
        self.enable()
        self.assertEqual(self.app.read_bytes(), before)
        self.assertIsNone(module.load(self.config).get('ThunksDB'))

    def test_wrong_i686_payload_is_rejected_without_mutation(self):
        before = self.config.read_bytes()
        lib = self.rootfs / self.prefix.lstrip('/') / 'lib/i386-linux-gnu/libvulkan_asahi.so'
        lib.write_bytes(b'\x7fELF\x02\x01' + bytes(14))
        with self.assertRaisesRegex(ValueError, 'Wrong ELF architecture'):
            self.enable()
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse(list(self.base.glob('mesa-default-backup.*')))

    def test_cache_generation_failure_leaves_all_files_untouched(self):
        self.cache_mock.side_effect = OSError('binfmt unavailable')
        before = self.config.read_bytes()
        with self.assertRaisesRegex(OSError, 'binfmt unavailable'):
            self.enable()
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual((self.rootfs / 'etc/ld.so.cache').read_bytes(), b'original-cache')
        self.assertFalse(list(self.base.glob('mesa-default-backup.*')))

    def test_user_graphics_defaults_win(self):
        self.config.write_text('{"Config":{"RootFS":' + json.dumps(str(self.rootfs)) +
                               ',"Env":"VK_LOADER_DRIVERS_SELECT=custom*.json"}}')
        self.enable()
        env = [v for k, v in module.load(self.config).get('Config') if k == 'Env']
        self.assertIn('VK_LOADER_DRIVERS_SELECT=custom*.json', env)
        self.assertNotIn('VK_LOADER_DRIVERS_SELECT=asahi*', env)

    def test_old_exclusive_default_must_be_rolled_back_first(self):
        self.config.write_text('{"Config":{"RootFS":' + json.dumps(str(self.rootfs)) +
                               ',"Env":"LD_LIBRARY_PATH=/opt/aurora-fex-mesa/old/lib"}}')
        with self.assertRaisesRegex(ValueError, 'Rollback the old'):
            self.enable()
        self.assertFalse(list(self.base.glob('mesa-default-backup.*')))


if __name__ == '__main__':
    unittest.main()
