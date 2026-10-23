import importlib.util
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('move_checkpoint',Path(__file__).resolve().parents[1]/'tools/move_checkpoint.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class MoveTests(unittest.TestCase):
    def test_wal_backup_and_active_queue_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'ai-platform'
            (root/'meetings').mkdir(parents=True)
            db=root/'meetings/jobs.sqlite3'
            with closing(sqlite3.connect(db)) as c:
                c.execute('PRAGMA journal_mode=WAL')
                c.execute('CREATE TABLE jobs (id TEXT,state TEXT)')
                c.execute("INSERT INTO jobs VALUES ('old-card','waiting_upload')")
                c.commit()
                result=m.inspect(root)
                self.assertTrue(result['idle'])
                dest=Path(tmp)/'checkpoint'
                m.snapshot(root,dest,result)
                with closing(sqlite3.connect(dest/'jobs.sqlite3')) as copy:
                    self.assertEqual(copy.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)
                c.execute("INSERT INTO jobs VALUES ('active','transcribing')")
                c.commit()
                self.assertFalse(m.inspect(root)['idle'])
                with self.assertRaises(RuntimeError):
                    m.snapshot(root,Path(tmp)/'blocked',m.inspect(root))
            self.assertFalse((Path(tmp)/'blocked').exists())
