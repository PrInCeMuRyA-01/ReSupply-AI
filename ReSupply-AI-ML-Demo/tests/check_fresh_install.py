"""A fresh backend ignores old database filenames and creates two empty shops."""
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile


def run():
    source=Path(__file__).resolve().parents[1]/'backend'
    with tempfile.TemporaryDirectory(prefix='easy-fresh-install-') as folder:
        backend=Path(folder)/'backend';backend.mkdir()
        for file in source.iterdir():
            if file.is_file() and file.suffix in {'.py','.js','.html','.css','.txt'}:
                shutil.copyfile(file,backend/file.name)
        old=backend/'resupply.db'
        with sqlite3.connect(old) as db:
            db.execute('CREATE TABLE products(id INTEGER PRIMARY KEY,name TEXT)')
            db.execute("INSERT INTO products VALUES(1,'Old shop sentinel - do not import')")
        digest=hashlib.sha256(old.read_bytes()).hexdigest()
        script='''import main
from shop_workspace import demo_scope
assert main.DB_PATH.name == 'resupply-easy.db'
assert main.DEMO_DB_PATH.name == 'resupply-ml-demo.db'
main.initialize_database()
with demo_scope():main.initialize_database()
for demo in (False,True):
    from contextlib import nullcontext
    with (demo_scope() if demo else nullcontext()):
        with main.database() as db:
            for table in ['products','sales','suppliers','supplier_quotes','purchase_orders','paypal_checkouts','daily_sales_history','demand_forecast_runs','stock_receipts']:
                assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0,table
print('Both new shops are empty.')
'''
        env={**os.environ,'PYTHONPATH':str(backend)+os.pathsep+os.environ.get('PYTHONPATH','')}
        result=subprocess.run([sys.executable,'-c',script],cwd=backend,env=env,capture_output=True,text=True)
        assert result.returncode==0,result.stdout+result.stderr
        assert hashlib.sha256(old.read_bytes()).hexdigest()==digest
        print('PASS: first startup uses new filenames, both shops contain zero user records, and old resupply.db is byte-for-byte unchanged.')


if __name__=='__main__':run()
