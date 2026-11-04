"""Online consistent SQLite backup; run in the app container."""
import argparse
import os
import sqlite3
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('destination', help='New .db path outside the source database')
args = p.parse_args()
source = Path(os.getenv('DB_PATH', '/data/project-hub.db')).resolve()
destination = Path(args.destination).resolve()
if not source.exists():
    p.error('source database does not exist')
if source == destination or destination.exists():
    p.error('destination must be a new file, different from source')
destination.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as src:
    with sqlite3.connect(destination) as dst:
        src.backup(dst)
        result = dst.execute('PRAGMA integrity_check').fetchone()[0]
        if result != 'ok':
            raise RuntimeError(result)
print(f'Backup saved: {destination}')
