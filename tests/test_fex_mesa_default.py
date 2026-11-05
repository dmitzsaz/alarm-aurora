"""Exercise reversible FEX selection, including FEX's repeated-key JSON format."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


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

    def test_default_is_idempotent_and_rollback_restores_exact_originals(self):
        before = {p: p.read_bytes() for p in (self.config, self.app)}
        backup = self.enable()
        settings = module.load(self.config).get('Config')
        env = [v for k, v in settings if k == 'Env']
        self.assertIn('KEEP=a', env)
        self.assertIn('KEEP_TOO=b', env)
        self.assertIn('VK_DRIVER_FILES=' + module.environment(self.prefix)['VK_DRIVER_FILES'], env)
        self.assertEqual([v for k, v in settings if k == 'HostEnv'], ['A=1', 'B=2'])
        thunks = module.load(self.app).get('ThunksDB')
        self.assertEqual((thunks.get('GL'), thunks.get('Vulkan'), thunks.get('asound')), (0, 0, 1))
        self.enable()
        self.assertEqual(len(list(self.base.glob('mesa-default-backup.*'))), 1)
        module.rollback(backup)
        for p, data in before.items():
            self.assertEqual(p.read_bytes(), data)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)

    def test_rollback_preflights_every_file_before_restoring_any(self):
        backup = self.enable()
        enabled = self.config.read_bytes()
        self.app.write_text(self.app.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'changed since activation'):
            module.rollback(backup)
        self.assertEqual(self.config.read_bytes(), enabled)

    def test_app_environment_gets_both_architectures_and_keeps_other_options(self):
        self.app.write_text('{"Config":{"Env":"APP=1","Env":"VK_DRIVER_FILES=/old.json","TSOEnabled":"1"}}')
        self.enable()
        settings = module.load(self.app).get('Config')
        env = [v for k, v in settings if k == 'Env']
        self.assertIn('APP=1', env)
        self.assertFalse(any('/old.json' in v for v in env))
        self.assertEqual(settings.get('TSOEnabled'), '1')
        self.assertTrue(any('asahi_icd.x86_64.json:' in v and 'asahi_icd.i686.json' in v for v in env))

    def test_wrong_i686_payload_is_rejected_without_mutation(self):
        before = self.config.read_bytes()
        lib = self.rootfs / self.prefix.lstrip('/') / 'lib/i386-linux-gnu/libvulkan_asahi.so'
        lib.write_bytes(b'\x7fELF\x02\x01' + bytes(14))
        with self.assertRaisesRegex(ValueError, 'Wrong ELF architecture'):
            self.enable()
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse(list(self.base.glob('mesa-default-backup.*')))

    def test_pattern_override_cannot_leave_stale_icds_selected(self):
        self.app.write_text('{"AppOverrides":{"game*":{"Env":"VK_ICD_FILENAMES=/old.json","Env":"OTHER=1"}},"Metadata":[{"keep":true}]}')
        self.enable()
        doc = module.load(self.app)
        override = doc.get('AppOverrides').get('game*')
        env = [v for k, v in override if k == 'Env']
        self.assertIn('OTHER=1', env)
        self.assertFalse(any('/old.json' in v for v in env))
        self.assertTrue(any(v.startswith('LD_LIBRARY_PATH=') for v in env))
        self.assertEqual(json.loads(self.app.read_text())['Metadata'], [{'keep': True}])


if __name__ == '__main__':
    unittest.main()
