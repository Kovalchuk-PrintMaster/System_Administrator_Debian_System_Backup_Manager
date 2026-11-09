import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

module_path = Path(__file__).resolve().parents[1] / 'scripts' / 'sbm.py'
spec = importlib.util.spec_from_file_location('sbm', module_path)
sbm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sbm)


class GuardsTest(unittest.TestCase):
    def test_part_device(self):
        self.assertEqual(sbm.part('/dev/sdg', 1), '/dev/sdg1')
        self.assertEqual(sbm.part('/dev/nvme0n1', 2), '/dev/nvme0n1p2')

    def test_snapshot_pattern(self):
        self.assertTrue(sbm.STAMP_RE.fullmatch('2026-11-09_13-01-02'))
        for name in ('../etc', '.incomplete-2026-11-09_13-01-02', 'today'):
            self.assertIsNone(sbm.STAMP_RE.fullmatch(name))

    def test_target_candidate_filters(self):
        fake = '{"blockdevices":[{"name":"sda","type":"disk","tran":"sata","size":250059350016,"model":"00AAKS-00F0A0"},{"name":"sdg","type":"disk","tran":"usb","size":250059350016,"model":"WDC WD25 00AAKS-00F0A0"},{"name":"sdh","type":"disk","tran":"usb","size":500000000000,"model":"00AAKS-00F0A0"}]}'
        with patch.object(sbm, 'call', return_value=fake):
            found = sbm.disk_candidates({'disk_model_token':'00AAKS-00F0A0', 'min_disk_bytes':249000000000, 'max_disk_bytes':251000000000})
        self.assertEqual(found, ['/dev/sdg'])

    def test_no_complete_snapshot_without_marker(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as p:
            base = Path(p)
            (base / '2026-11-09_13-01-02').mkdir()
            self.assertEqual(sbm.snapshots(base), [])
            (base / '2026-11-09_13-01-02' / '.sbm-complete.json').write_text('{}')
            self.assertEqual(len(sbm.snapshots(base)), 1)

    def test_excludes_durable_forprint_states(self):
        self.assertFalse(any('/var/lib/forprint' in v for v in sbm.EXCLUDE_SYSTEM))
        self.assertFalse(any('/.state/' in v or '/.runtime/' in v for v in sbm.EXCLUDE_DEV))

if __name__ == '__main__':
    unittest.main()
