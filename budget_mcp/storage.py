"""Single-user local repository. Never instantiated by the public HTTP profile."""
from pathlib import Path
from contextlib import contextmanager
import json, sqlite3, hashlib, threading, re, os
from datetime import datetime, timezone
from .money import BudgetError

class Store:
    def __init__(self,root):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.inputs=self.root/'inputs';self.outputs=self.root/'outputs'
        self.inputs.mkdir(exist_ok=True);self.outputs.mkdir(exist_ok=True)
        self.db=self.root/'budget.sqlite3';self.lock=threading.RLock()
        if self.db.is_symlink() or self.inputs.is_symlink() or self.outputs.is_symlink():
            raise BudgetError('저장 경로에 심볼릭 링크를 사용할 수 없습니다.')
        with self.connection() as con:
            con.execute('CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY, payload TEXT NOT NULL, created TEXT NOT NULL)')
            con.execute('CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, payload TEXT NOT NULL, created TEXT NOT NULL)')
        try:os.chmod(self.db,0o600)
        except OSError:pass
    @contextmanager
    def connection(self):
        c=sqlite3.connect(self.db,timeout=15)
        try:
            c.execute('PRAGMA foreign_keys=ON')
            with c: yield c
        finally: c.close()
    def put(self,table,obj,ident=None):
        if table not in ('datasets','reports'):raise BudgetError('저장 대상 오류')
        raw=json.dumps(obj,ensure_ascii=False,sort_keys=True,allow_nan=False)
        ident=ident or hashlib.sha256(raw.encode()).hexdigest()[:24]
        if not re.fullmatch('[a-f0-9]{24}',ident):raise BudgetError('ID 형식 오류')
        with self.lock, self.connection() as c:
            if len(raw.encode())>60*1024*1024:raise BudgetError('자료 저장 크기 초과')
            old=c.execute(f'SELECT 1 FROM {table} WHERE id=?',(ident,)).fetchone()
            if not old:
                if self.db.stat().st_size+len(raw.encode())>256*1024*1024:raise BudgetError('작업공간 256MB 제한: 불필요 자료를 삭제하세요.')
                if c.execute(f'SELECT count(*) FROM {table}').fetchone()[0]>=100:raise BudgetError('저장 자료 100개 제한')
            c.execute(f'INSERT OR IGNORE INTO {table} VALUES(?,?,?)',(ident,raw,datetime.now(timezone.utc).isoformat()))
        return ident
    def get(self,table,ident):
        if table not in ('datasets','reports') or not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{24}',ident):raise BudgetError('자료 ID 오류')
        with self.connection() as c:r=c.execute(f'SELECT payload FROM {table} WHERE id=?',(ident,)).fetchone()
        if not r:raise BudgetError('자료 ID를 찾지 못했습니다.')
        return json.loads(r[0])
    def list(self):
        with self.connection() as c:rows=c.execute('SELECT id,payload,created FROM datasets ORDER BY created DESC').fetchall()
        return [{'dataset_id':id,'meta':json.loads(payload)['meta'],'created':created,'row_count':len(json.loads(payload)['rows'])} for id,payload,created in rows]
    def delete(self,ident,confirm):
        if confirm is not True:raise BudgetError('삭제는 confirm=true가 필요합니다.')
        self.get('datasets',ident)
        removed=[]
        with self.lock,self.connection() as c:
            for rid,payload in c.execute('SELECT id,payload FROM reports').fetchall():
                if ident in json.loads(payload).get('dataset_ids',[]):
                    c.execute('DELETE FROM reports WHERE id=?',(rid,));removed.append(rid)
            c.execute('DELETE FROM datasets WHERE id=?',(ident,))
        for rid in removed:
            for ext in ('json','csv','html'):
                p=self.outputs/(rid+'.'+ext)
                if p.is_file() and not p.is_symlink():p.unlink()
        # Secure erasure is not promised; compact logical DB after deletion.
        with self.lock,self.connection() as c:c.execute('VACUUM')
        return {'deleted_dataset':ident,'deleted_related_reports':removed,
                'source_files_deleted':False,'note':'원본 inputs 파일은 삭제하지 않습니다. 디스크 백업/복구영역의 보안삭제는 보장하지 않습니다.'}

