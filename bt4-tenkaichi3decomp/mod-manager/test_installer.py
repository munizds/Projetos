import io
import csv
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from mod_installer import scan, install, undo, csv_report, source_members, validate_game


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.game = self.root / 'game'
        for n in ('pzs3us0', 'pzs3us1', 'pzs3us2'):
            (self.game / 'gamedata' / n).mkdir(parents=True)
        (self.game / 'gamedata' / 'pzs3us1' / '00000.bin').write_bytes(b'ORIGINAL-A')
        (self.game / 'gamedata' / 'pzs3us1' / '00001.bin').write_bytes(b'ORIGINAL-B')
        self.folder = self.root / 'mod'
        self.folder.mkdir()

    def make_afs(self, out, values):
        n = len(values)
        header = b'AFS\0' + struct.pack('<I', n)
        pos = 8 + n * 8
        entries = []
        for v in values:
            entries.append((pos, len(v)))
            pos += len(v)
        payload = header + b''.join(struct.pack('<II', *entry) for entry in entries) + b''.join(values)
        out.write_bytes(payload)

    def test_zip_loose_installs_undoes_and_preserves_original(self):
        pack = self.root / 'mod.zip'
        with zipfile.ZipFile(pack, 'w') as z:
            z.writestr('BT4/songs/theme.mp3', b'MP3-sample')
            z.writestr('BT4/textures/abc.png', b'PNG-sample')
            z.writestr('BT4/random.dat', b'not known')
        rows = scan(pack, self.game)
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(c.checked for c in rows), 2)
        transaction = install(self.game, rows, {i for i,c in enumerate(rows) if c.checked})
        self.assertEqual((self.game / 'songs/theme.mp3').read_bytes(), b'MP3-sample')
        self.assertEqual((self.game / 'textures/abc.png').read_bytes(), b'PNG-sample')
        self.assertEqual(undo(self.game, transaction), 2)
        self.assertFalse((self.game / 'songs/theme.mp3').exists())
        self.assertFalse((self.game / 'textures/abc.png').exists())
        self.assertEqual((self.game / 'gamedata/pzs3us1/00000.bin').read_bytes(), b'ORIGINAL-A')

    def test_afs_detects_same_original_and_requires_opt_in(self):
        afs = self.folder / 'PZS4US1.AFS'
        self.make_afs(afs, [b'ORIGINAL-A', b'CHANGED-B', b'NEW-C'])
        rows = scan(afs, self.game)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].status, 'IDENTICO AO BT3')
        self.assertEqual(rows[1].risk, 'experimental')
        self.assertEqual(rows[2].risk, 'experimental')
        with self.assertRaises(ValueError):
            install(self.game, rows, {1})
        txn = install(self.game, rows, {1}, allow_experimental=True)
        self.assertEqual((self.game / 'gamedata/mods/pzs3us1/00001.bin').read_bytes(), b'CHANGED-B')
        self.assertEqual((self.game / 'gamedata/pzs3us1/00001.bin').read_bytes(), b'ORIGINAL-B')
        self.assertEqual(undo(self.game, txn), 1)

    def test_conflict_installed_backup_and_undo(self):
        original = self.game / 'songs/theme.adx'
        original.parent.mkdir()
        original.write_bytes(b'ORIGINAL-EXISTING')
        modified = self.folder / 'songs/theme.adx'
        modified.parent.mkdir()
        modified.write_bytes(b'NEW-ADDED')
        rows = scan(self.folder, self.game)
        self.assertEqual(rows[0].status, 'SUBSTITUI OVERRIDE')
        txn = install(self.game, rows, {0})
        self.assertEqual(original.read_bytes(), b'NEW-ADDED')
        # Se outro app alterou o arquivo depois, nao destrua alteracao de terceiros.
        original.write_bytes(b'THIRD-PARTY')
        with self.assertRaises(ValueError):
            undo(self.game, txn)
        original.write_bytes(b'NEW-ADDED')
        undo(self.game, txn)
        self.assertEqual(original.read_bytes(), b'ORIGINAL-EXISTING')

    def test_zip_slip_blocked(self):
        zpath = self.root / 'attack.zip'
        with zipfile.ZipFile(zpath, 'w') as z:
            z.writestr('../songs/evil.adx', b'evil')
        with self.assertRaises(ValueError):
            source_members(zpath)

    def test_report_contains_all(self):
        p = self.folder / 'songs' / 'sound.mp3'
        p.parent.mkdir()
        p.write_bytes(b'track')
        rows = scan(self.folder, self.game)
        dest = self.root / 'report.csv'
        csv_report(rows, dest)
        with dest.open('r', encoding='utf-8-sig', newline='') as f:
            self.assertEqual(len(list(csv.DictReader(f))), 1)

    def test_iso_scan_afs(self):
        # ISO9660 minimo montado somente para testar o interpretador de ISO.
        afs = self.folder / 'PZS4US1.AFS'
        self.make_afs(afs, [b'CHANGED-A'])
        afsbytes = afs.read_bytes()
        iso = self.root / 'test.iso'
        data = bytearray(40 * 2048)
        def rec(lba, size, flags, name):
            namebytes = name if isinstance(name, bytes) else name.encode('ascii')
            n = 33 + len(namebytes) + (len(namebytes)%2 == 0)
            b = bytearray(n)
            b[0] = n
            b[2:6] = lba.to_bytes(4, 'little')
            b[6:10] = lba.to_bytes(4, 'big')
            b[10:14] = size.to_bytes(4, 'little')
            b[14:18] = size.to_bytes(4, 'big')
            b[25] = flags
            b[28:30] = (1).to_bytes(2, 'little')
            b[30:32] = (1).to_bytes(2, 'big')
            b[32] = len(namebytes)
            b[33:33+len(namebytes)] = namebytes
            return bytes(b)
        pvd = 16 * 2048
        data[pvd:pvd+7] = b'\x01CD001\x01'
        data[pvd+156:pvd+156+34] = rec(20, 2048, 2, b'\x00')
        rootrec = rec(21, 2048, 2, 'DATA')
        data[20*2048:20*2048+len(rootrec)] = rootrec
        afsrec = rec(22, len(afsbytes), 0, 'PZS4US1.AFS;1')
        data[21*2048:21*2048+len(afsrec)] = afsrec
        data[22*2048:22*2048+len(afsbytes)] = afsbytes
        iso.write_bytes(data)
        rows = scan(iso, self.game)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].category, 'AFS BT4')
        self.assertEqual(rows[0].status, 'REVISAR - EXPERIMENTAL')


if __name__ == '__main__':
    unittest.main(verbosity=2)