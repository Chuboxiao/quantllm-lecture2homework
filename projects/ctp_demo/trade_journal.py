"""Durable intent-before-send, one open and one close; also excludes parallel runs."""
import fcntl,json,sqlite3
from pathlib import Path

class Journal:
 def __init__(self,path):
  path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
  self.lock=path.with_suffix('.lock').open('a')
  try:fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except OSError:
   self.lock.close();raise RuntimeError('Another trading/inspection process holds this account lock')
  self.db=sqlite3.connect(path)
  self.db.execute('PRAGMA synchronous=FULL')
  self.db.execute('CREATE TABLE IF NOT EXISTS intents(role TEXT PRIMARY KEY, payload TEXT NOT NULL)')
  self.db.execute('CREATE TABLE IF NOT EXISTS fills(identity TEXT PRIMARY KEY, payload TEXT NOT NULL)')
  self.db.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
  self.db.commit()
 def reserve(self,role,payload):
  # COMMIT precedes the API call. Crash/timeout never grants a second send.
  with self.db:self.db.execute('INSERT INTO intents VALUES (?,?)',(role,json.dumps(payload)))
 def intents(self):return {k:json.loads(v) for k,v in self.db.execute('SELECT role,payload FROM intents')}
 def fill(self,identity,payload):
  with self.db:
   cur=self.db.execute('INSERT OR IGNORE INTO fills VALUES (?,?)',(identity,json.dumps(payload)))
  return cur.rowcount==1
 def put(self,key,value):
  with self.db:self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',(key,json.dumps(value)))
 def get(self,key,default=None):
  row=self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
  return json.loads(row[0]) if row else default
 def close(self):self.db.close();self.lock.close()
