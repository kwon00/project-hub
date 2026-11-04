import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import zipfile
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape

from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator, ValidationInfo

DB_PATH = os.getenv('DB_PATH', '/data/project-hub.db')
STATIC = Path(__file__).parent / 'static'
STATES = Literal['예정', '진행 중', '검토 중', '보류', '완료']
PRIORITIES = Literal['낮음', '보통', '높음', '긴급']
login_attempts = {}
login_lock = threading.Lock()

@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def now():
    return datetime.now(timezone.utc).isoformat()

DEFAULT_THIRD_PARTY_STEPS = ['업체 컨택하기', '설치 일자 확정', '설치 전 구성 확인(OS, 디스크, 스펙, 특이사항 등)', '솔루션 설치 파일 수신', '솔루션 적용 완료', '매뉴얼/가이드 수신', '구축 완료 보고서 수신']

def checklist_progress(tasks):
    total = len(tasks)
    done = sum(bool(t['done']) for t in tasks)
    return (done * 100 + total // 2) // total if total else 0

def third_party_status(progress):
    return '완료' if progress == 100 else ('진행 중' if progress else '예정')

def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript('''
        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, client TEXT NOT NULL,
          owner TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
          status TEXT NOT NULL, description TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS items (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          kind TEXT NOT NULL, title TEXT NOT NULL, vendor TEXT NOT NULL, owner TEXT NOT NULL,
          start TEXT NOT NULL, end TEXT NOT NULL, status TEXT NOT NULL,
          priority TEXT NOT NULL, progress INTEGER NOT NULL, notes TEXT NOT NULL,
          updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS items_project ON items(project_id);
        CREATE TABLE IF NOT EXISTS activity (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          message TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
          password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
          session_version INTEGER NOT NULL DEFAULT 1);
        PRAGMA user_version=4;
        ''')
        project_columns = {row['name'] for row in con.execute('PRAGMA table_info(projects)')}
        if 'color' not in project_columns:
            con.execute("ALTER TABLE projects ADD COLUMN color TEXT NOT NULL DEFAULT '#4f8064'")
        columns = {row['name'] for row in con.execute('PRAGMA table_info(activity)')}
        for column in ['actor_id', 'actor_username', 'actor_name']:
            if column not in columns:
                con.execute(f"ALTER TABLE activity ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")

        item_columns = {row['name'] for row in con.execute('PRAGMA table_info(items)')}
        for column, declaration in [('installed_at', "TEXT NOT NULL DEFAULT ''"),
                                    ('developer_applied', 'INTEGER NOT NULL DEFAULT 0'),
                                    ('checklist', "TEXT NOT NULL DEFAULT '[]'")]:
            if column not in item_columns:
                con.execute(f'ALTER TABLE items ADD COLUMN {column} {declaration}')
        # Preserve old partner titles/notes as a child checklist, keeping IDs and dates.
        for row in con.execute("SELECT * FROM items WHERE kind='partner'").fetchall():
            tasks = [{'id': secrets.token_hex(10), 'text': row['title'] + ('\n' + row['notes'] if row['notes'] else ''), 'done': row['status'] == '완료'}]
            con.execute("UPDATE items SET kind='third_party',title=?,checklist=? WHERE id=?",
                        (row['vendor'] or row['title'], json.dumps(tasks, ensure_ascii=False), row['id']))

        # Recalculate existing percentages without adding/replacing checklist entries.
        for row in con.execute("SELECT id,checklist,progress,status FROM items WHERE kind='third_party'").fetchall():
            value = checklist_progress(json.loads(row['checklist']))
            status = third_party_status(value)
            if value != row['progress'] or status != row['status']:
                con.execute('UPDATE items SET progress=?,status=? WHERE id=?', (value, status, row['id']))

def hash_password(password):
    if len(password) < 12:
        raise ValueError('비밀번호는 12자 이상이어야 합니다.')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'

def verify_password(password, encoded):
    try:
        algorithm, rounds, salt, digest = encoded.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(rounds)).hex()
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError):
        return False

def bootstrap_admin():
    with db() as con:
        if not con.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            con.execute('INSERT INTO users(id,username,name,password_hash) VALUES(?,?,?,?)',
                        (secrets.token_hex(12), os.getenv('APP_ADMIN_USERNAME', 'admin'),
                         os.getenv('APP_ADMIN_NAME', '관리자'), hash_password(config()[0])))

def config():
    password = os.getenv('APP_PASSWORD', '')
    key = os.getenv('SESSION_SECRET', '')
    if len(password) < 12 or len(key) < 32:
        raise RuntimeError('APP_PASSWORD must have 12+ characters and SESSION_SECRET must have 32+ characters.')
    return password, key

@asynccontextmanager
async def lifespan(app):
    config()
    init_db()
    bootstrap_admin()
    yield

app = FastAPI(title='Project Hub', version='1.0.0', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount('/static', StaticFiles(directory=STATIC), name='static')

@app.middleware('http')
async def headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control'] = 'no-store'
    return response

def auth(request: Request):
    token = request.cookies.get('ph_session', '')
    try:
        payload, signature = token.split('.')
        expected = hmac.new(config()[1].encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        session = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        if session['exp'] < time.time():
            raise ValueError()
        with db() as con:
            user = con.execute('SELECT id,username,name,active,session_version FROM users WHERE id=?', (session['uid'],)).fetchone()
        if not user or not user['active'] or session['version'] != user['session_version']:
            raise ValueError()
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise HTTPException(401, '로그인이 필요합니다.')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('x-requested-with') != 'ProjectHub':
        raise HTTPException(403, '잘못된 요청입니다.')
    return {'id': user['id'], 'username': user['username'], 'name': user['name']}

class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(max_length=1024)

@app.post('/api/login')
def login(body: Login, request: Request, response: Response):
    address = request.client.host if request.client else 'unknown'
    with db() as con:
        user = con.execute('SELECT * FROM users WHERE username=?', (body.username,)).fetchone()
    with login_lock:
        cutoff = time.time() - 300
        for k in list(login_attempts):
            login_attempts[k] = [t for t in login_attempts[k] if t > cutoff]
            if not login_attempts[k]:
                del login_attempts[k]
        attempts = login_attempts.setdefault(address, [])
        if len(attempts) >= 10:
            raise HTTPException(429, '로그인 시도가 많습니다. 5분 후 다시 시도하세요.')
        # Use the same KDF work for nonexistent accounts to avoid username timing disclosure.
        encoded = user['password_hash'] if user else 'pbkdf2_sha256$600000$missing-account$' + '0' * 64
        valid = verify_password(body.password, encoded)
        if not user or not user['active'] or not valid:
            attempts.append(time.time())
            raise HTTPException(401, '계정 또는 비밀번호를 확인하세요.')
        login_attempts.pop(address, None)
    payload = base64.urlsafe_b64encode(json.dumps({'uid': user['id'], 'exp': int(time.time()) + 43200,
                                                 'version': user['session_version']}).encode()).decode().rstrip('=')
    signature = hmac.new(config()[1].encode(), payload.encode(), hashlib.sha256).hexdigest()
    response.set_cookie('ph_session', payload + '.' + signature, httponly=True, samesite='strict', secure=os.getenv('COOKIE_SECURE', 'true').lower() == 'true', max_age=43200)
    return {'ok': True}

@app.get('/api/me')
def me(user=Depends(auth)):
    return user

@app.post('/api/logout', dependencies=[Depends(auth)])
def logout(response: Response):
    response.delete_cookie('ph_session')
    return {'ok': True}

class Project(BaseModel):
    name: str = Field(default='', max_length=160)
    client: str = Field(default='', max_length=160)
    owner: str = Field(default='', max_length=100)
    start: date | None = None
    end: date | None = None
    status: STATES = '예정'
    description: str = Field(default='', max_length=10000)
    color: str = Field(default='#4f8064', pattern=r'^#[0-9a-fA-F]{6}$')

    @model_validator(mode='after')
    def check(self, info: ValidationInfo):
        importing = bool(info.context and info.context.get('excel_import'))
        if not importing and (not self.start or not self.end):
            raise ValueError('시작일과 종료일을 입력하세요.')
        if self.start and self.end and self.end < self.start:
            raise ValueError('종료일은 시작일 이후여야 합니다.')
        if not importing and not self.name.strip():
            raise ValueError('프로젝트명을 입력하세요.')
        self.color = self.color.lower()
        return self

class ChecklistEntry(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=2000)
    done: bool = False

    @model_validator(mode='after')
    def check(self):
        if not self.text.strip():
            raise ValueError('진행사항 내용을 입력하세요.')
        return self

class Item(BaseModel):
    kind: Literal['schedule', 'third_party', 'developer']
    title: str = Field(default='', max_length=200)
    vendor: str = Field(default='', max_length=160)
    owner: str = Field(default='', max_length=100)
    start: date | None = None
    end: date | None = None
    status: STATES = '예정'
    priority: PRIORITIES = '보통'
    progress: int = Field(default=0, ge=0, le=100)
    notes: str = Field(default='', max_length=15000)
    installed_at: date | None = None
    developer_applied: bool = False
    checklist: list[ChecklistEntry] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def check(self, info: ValidationInfo):
        importing = bool(info.context and info.context.get('excel_import'))
        if not importing and not self.title.strip():
            raise ValueError('이름 또는 제목을 입력하세요.')
        if self.kind != 'third_party':
            if self.kind == 'schedule' and not importing and (self.start is None or self.end is None):
                raise ValueError('시작일과 마감일을 입력하세요.')
            if self.start and self.end and self.end < self.start:
                raise ValueError('시작일과 마감일을 확인하세요.')
            if not importing and self.kind == 'developer' and not self.vendor.strip():
                raise ValueError('개발사명을 입력하세요.')
            if self.status == '완료':
                self.progress = 100
            elif self.progress == 100:
                raise ValueError('진행률 100%는 완료 상태로 설정하세요.')
            if self.checklist or self.developer_applied or self.installed_at:
                raise ValueError('설치 및 체크리스트는 3rd-party 항목에서만 사용할 수 있습니다.')
        else:
            if self.start and self.end and self.end < self.start:
                raise ValueError('종료일은 시작일 이후여야 합니다.')
            if 'checklist' not in self.model_fields_set:
                self.checklist = [ChecklistEntry(id=secrets.token_hex(12), text=text) for text in DEFAULT_THIRD_PARTY_STEPS]
            self.progress = checklist_progress([entry.model_dump() for entry in self.checklist])
            self.status = third_party_status(self.progress)
            if len({entry.id for entry in self.checklist}) != len(self.checklist):
                raise ValueError('진행사항 ID가 중복됩니다.')
        return self

def item_fields(body):
    fields = body.model_dump(mode='json')
    fields['checklist'] = json.dumps(fields['checklist'], ensure_ascii=False)
    fields['developer_applied'] = int(fields['developer_applied'])
    for key in ['start', 'end', 'installed_at']:
        fields[key] = fields[key] or ''
    return fields

def item_dict(row):
    result = dict(row)
    result['checklist'] = json.loads(result['checklist'])
    result['developer_applied'] = bool(result['developer_applied'])
    if result['kind'] == 'third_party':
        result['progress'] = checklist_progress(result['checklist'])
        result['status'] = third_party_status(result['progress'])
    return result

def record(con, pid, text, actor=None):
    actor = actor or {'id': '', 'username': '', 'name': '기록 없음 (기존 데이터)'}
    con.execute('INSERT INTO activity(project_id,message,created_at,actor_id,actor_username,actor_name) VALUES(?,?,?,?,?,?)',
                (pid, text, now(), actor['id'], actor['username'], actor['name']))

def require_project(con, pid):
    if not con.execute('SELECT id FROM projects WHERE id=?', (pid,)).fetchone():
        raise HTTPException(404, '프로젝트를 찾을 수 없습니다.')

@app.get('/healthz')
def health():
    return {'status': 'ok'}

@app.get('/readyz')
def ready():
    with db() as con:
        con.execute('SELECT 1 FROM projects LIMIT 1')
    return {'status': 'ready'}

@app.get('/')
def index():
    return FileResponse(STATIC / 'index.html')

@app.get('/api/data', dependencies=[Depends(auth)])
def data():
    with db() as con:
        return {table: [(item_dict(r) if table == 'items' else dict(r)) for r in con.execute(f'SELECT * FROM {table} ORDER BY {order}')] for table, order in [('projects', 'created_at DESC'), ('items', 'end ASC'), ('activity', 'id DESC LIMIT 500')]}

@app.post('/api/projects', status_code=201, dependencies=[Depends(auth)])
def create_project(body: Project, actor=Depends(auth)):
    pid = secrets.token_hex(12)
    fields = body.model_dump(mode='json')
    with db() as con:
        values = {'id': pid, **fields, 'created_at': now()}
        con.execute('INSERT INTO projects (' + ','.join(values) + ') VALUES (' + ','.join('?' for _ in values) + ')', tuple(values.values()))
        record(con, pid, f'프로젝트 생성 · {body.name}', actor)
    return {'id': pid}

@app.put('/api/projects/{pid}', dependencies=[Depends(auth)])
def edit_project(pid: str, body: Project, actor=Depends(auth)):
    fields = body.model_dump(mode='json')
    with db() as con:
        require_project(con, pid)
        con.execute('UPDATE projects SET ' + ','.join(k+'=?' for k in fields) + ' WHERE id=?', (*fields.values(), pid))
        record(con, pid, f'프로젝트 수정 · {body.name}', actor)
    return {'ok': True}

@app.delete('/api/projects/{pid}', dependencies=[Depends(auth)])
def delete_project(pid: str):
    with db() as con:
        require_project(con, pid)
        con.execute('DELETE FROM projects WHERE id=?', (pid,))
    return {'ok': True}

@app.post('/api/projects/{pid}/items', status_code=201, dependencies=[Depends(auth)])
def create_item(pid: str, body: Item, actor=Depends(auth)):
    iid = secrets.token_hex(12)
    with db() as con:
        require_project(con, pid)
        fields = {'id': iid, 'project_id': pid, **item_fields(body), 'updated_at': now()}
        con.execute('INSERT INTO items (' + ','.join(fields) + ') VALUES (' + ','.join('?' for _ in fields) + ')', tuple(fields.values()))
        record(con, pid, f'{ {"schedule": "일정", "third_party": "3rd-party", "developer": "개발사 업무"}[body.kind]} 등록 · {body.title}', actor)
    return {'id': iid}

@app.put('/api/items/{iid}', dependencies=[Depends(auth)])
def edit_item(iid: str, body: Item, actor=Depends(auth)):
    fields = item_fields(body)
    with db() as con:
        old = con.execute('SELECT * FROM items WHERE id=?', (iid,)).fetchone()
        if not old:
            raise HTTPException(404, '업무를 찾을 수 없습니다.')
        if old['kind'] != body.kind:
            raise HTTPException(422, '업무 유형은 변경할 수 없습니다.')
        con.execute('UPDATE items SET ' + ','.join(k+'=?' for k in fields) + ',updated_at=? WHERE id=?', (*fields.values(), now(), iid))
        record(con, old['project_id'], f'업무 수정 · {body.title} / {body.status} / {body.progress}%', actor)
    return {'ok': True}

@app.delete('/api/items/{iid}', dependencies=[Depends(auth)])
def delete_item(iid: str, actor=Depends(auth)):
    with db() as con:
        old = con.execute('SELECT * FROM items WHERE id=?', (iid,)).fetchone()
        if not old:
            raise HTTPException(404, '업무를 찾을 수 없습니다.')
        record(con, old['project_id'], f'업무 삭제 · {old["title"]}', actor)
        con.execute('DELETE FROM items WHERE id=?', (iid,))
    return {'ok': True}

class Toggle(BaseModel):
    done: bool

@app.patch('/api/items/{iid}/checklist/{cid}', dependencies=[Depends(auth)])
def toggle_checklist(iid: str, cid: str, body: Toggle, actor=Depends(auth)):
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute("SELECT * FROM items WHERE id=? AND kind='third_party'", (iid,)).fetchone()
        if not row:
            raise HTTPException(404, '3rd-party를 찾을 수 없습니다.')
        tasks = json.loads(row['checklist'])
        entry = next((t for t in tasks if t['id'] == cid), None)
        if entry is None:
            raise HTTPException(404, '진행사항을 찾을 수 없습니다.')
        if entry['done'] != body.done:
            entry['done'] = body.done
            value = checklist_progress(tasks)
            con.execute('UPDATE items SET checklist=?,progress=?,status=?,updated_at=? WHERE id=?',
                        (json.dumps(tasks, ensure_ascii=False), value, third_party_status(value), now(), iid))
            record(con, row['project_id'], f'3rd-party 진행사항 {"완료" if body.done else "완료 취소"} · {row["title"]} · {entry["text"]}', actor)
    return {'ok': True}

@app.patch('/api/items/{iid}/application', dependencies=[Depends(auth)])
def toggle_application(iid: str, body: Toggle, actor=Depends(auth)):
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute("SELECT * FROM items WHERE id=? AND kind='third_party'", (iid,)).fetchone()
        if not row:
            raise HTTPException(404, '3rd-party를 찾을 수 없습니다.')
        if bool(row['developer_applied']) != body.done:
            con.execute('UPDATE items SET developer_applied=?,updated_at=? WHERE id=?', (int(body.done), now(), iid))
            record(con, row['project_id'], f'개발사 적용 {"완료" if body.done else "완료 취소"} · {row["title"]}', actor)
    return {'ok': True}

# Native XLSX generated with the standard library. User text is always inlineStr,
# never formula XML. Dates are Excel numeric serials; percentages are numeric.
def workbook(sheets):
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    out = io.BytesIO()
    def clean(value):
        return ''.join(c for c in str(value) if c in '\t\n\r' or 0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)
    def col(n):
        result = ''
        while n:
            n, r = divmod(n-1, 26)
            result = chr(65+r) + result
        return result
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,len(sheets)+1)) + '</Types>')
        z.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,rows) in enumerate(sheets,1)) + '</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(sheets)+1)) + '<Relationship Id="styles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml', f'<styleSheet xmlns="{ns}"><fonts count="2"><font><sz val="11"/><name val="맑은 고딕"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="맑은 고딕"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF163B35"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="4"><xf fontId="0" fillId="0" borderId="0" xfId="0"><alignment vertical="top" wrapText="1"/></xf><xf fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf fontId="0" fillId="0" borderId="0" numFmtId="14" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf fontId="0" fillId="0" borderId="0" numFmtId="9" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        for i, (name, rows) in enumerate(sheets, 1):
            xml = []
            for r, row in enumerate(rows, 1):
                cells = []
                for c, value in enumerate(row, 1):
                    ref = f'{col(c)}{r}'
                    if isinstance(value, dict) and 'checklist' in value:
                        runs = ''.join('<r><rPr>' + ('<strike/>' if t['done'] else '') + '</rPr><t xml:space="preserve">' + escape(clean(('● ' if t['done'] else '○ ') + t['text'] + ('\n' if j + 1 < len(value['checklist']) else ''))) + '</t></r>' for j, t in enumerate(value['checklist']))
                        cells.append(f'<c r="{ref}" s="0" t="inlineStr"><is>{runs}</is></c>' if runs else f'<c r="{ref}" s="0" t="inlineStr"><is><t/></is></c>')
                    elif isinstance(value, date):
                        cells.append(f'<c r="{ref}" s="2"><v>{(value-date(1899,12,30)).days}</v></c>')
                    elif isinstance(value, (int,float)):
                        cells.append(f'<c r="{ref}" s="3"><v>{value}</v></c>')
                    else:
                        cells.append(f'<c r="{ref}" s="{1 if r==1 else 0}" t="inlineStr"><is><t xml:space="preserve">{escape(clean(value))}</t></is></c>')
                lengths = [sum(max(1, (len(line) + 19) // 20) for line in ('\n'.join(t['text'] for t in v['checklist']) if isinstance(v, dict) else str(v)).split('\n')) for v in row]
                height = 28 if r == 1 else min(409, max(42, 16 * max(lengths) + 8))
                xml.append(f'<row r="{r}" ht="{height}" customHeight="1">' + ''.join(cells) + '</row>')
            visible = next((i for i, value in enumerate(rows[0]) if str(value).startswith('_')), len(rows[0]))
            last = f'{col(len(rows[0]))}{len(rows)}'
            filtered_last = f'{col(visible)}{len(rows)}'
            columns = f'<col min="1" max="{visible}" width="23" customWidth="1"/>'
            if visible < len(rows[0]):
                columns += f'<col min="{visible+1}" max="{len(rows[0])}" width="20" customWidth="1" hidden="1"/>'
            z.writestr(f'xl/worksheets/sheet{i}.xml', f'<worksheet xmlns="{ns}"><dimension ref="A1:{last}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>{columns}</cols><sheetData>' + ''.join(xml) + f'</sheetData><autoFilter ref="A1:{filtered_last}"/></worksheet>')
    return out.getvalue()

def export_filename(project_name, scope):
    label = {'project': '프로젝트', 'calendar': '일정', 'third_party': '3rd-party', 'developer': '개발사'}[scope]
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', project_name).strip(' .') or '프로젝트'
    return f'{safe[:120]}_{label}_{datetime.now(timezone(timedelta(hours=9))).date().isoformat()}.xlsx'

@app.get('/api/export.xlsx', dependencies=[Depends(auth)])
def export(project_id: str | None = None, scope: Literal['calendar', 'project', 'third_party', 'developer'] = 'project'):
    if scope == 'project' and not project_id:
        raise HTTPException(422, '프로젝트를 지정하세요.')
    with db() as con:
        if project_id:
            require_project(con, project_id)
        projects = [dict(r) for r in con.execute('SELECT * FROM projects' + (' WHERE id=?' if project_id else ''), (project_id,) if project_id else ())]
        items = [item_dict(r) for r in con.execute('SELECT * FROM items' + (' WHERE project_id=?' if project_id else '') + ' ORDER BY end', (project_id,) if project_id else ())]
        activity = [dict(r) for r in con.execute('SELECT * FROM activity' + (' WHERE project_id=?' if project_id else '') + ' ORDER BY id DESC', (project_id,) if project_id else ())] if scope == 'project' else []
    names = {p['id']: p['name'] for p in projects}
    def typed_date(s):
        return date.fromisoformat(s) if s else ''
    def item_rows(selected, include_kind=False):
        header = ['프로젝트'] + (['유형'] if include_kind else []) + ['제목','개발사','담당자','시작일','마감일','상태','우선순위','진행률','메모','최근 수정(UTC)','_project_id','_record_id']
        labels = {'schedule': '일정', 'developer': '개발사', 'third_party': '3rd-party 설치'}
        return [header] + [[names[x['project_id']]] + ([labels[x['kind']]] if include_kind else []) +
                          [x['title'],x['vendor'],x['owner'],typed_date(x['start']),typed_date(x['end']),x['status'],x['priority'],x['progress']/100,x['notes'],x['updated_at'],x['project_id'],x['id']] for x in selected]
    third_rows = [['프로젝트','3rd-party 이름','설치 일자','개발사 적용 완료','담당자','우선순위','진행률','진행사항','메모','최근 수정(UTC)','_project_id','_record_id']] + [[names[x['project_id']],x['title'],typed_date(x['installed_at']),'완료' if x['developer_applied'] else '미완료',x['owner'],x['priority'],x['progress']/100,{'checklist': x['checklist']},x['notes'],x['updated_at'],x['project_id'],x['id']] for x in items if x['kind']=='third_party']
    if scope == 'calendar':
        calendar_items = [dict(x, start=x['installed_at'], end=x['installed_at']) if x['kind']=='third_party' else x for x in items if x['kind']!='third_party' or x['installed_at']]
        sheets = [('일정', item_rows(calendar_items, True))]
    elif scope == 'third_party':
        sheets = [('3rd-party', third_rows)]
    elif scope == 'developer':
        sheets = [('개발사', item_rows([x for x in items if x['kind'] == 'developer']))]
    else:
        overview = [['프로젝트명','고객사','담당자','시작일','종료일','상태','설명','_project_id']] + [[p['name'],p['client'],p['owner'],typed_date(p['start']),typed_date(p['end']),p['status'],p['description'],p['id']] for p in projects]
        sheets = [('개요', overview), ('일정', item_rows([x for x in items if x['kind'] == 'schedule'])),
                  ('3rd-party', third_rows), ('개발사', item_rows([x for x in items if x['kind'] == 'developer'])),
                  ('변경이력', [['프로젝트','내용','변경 계정','계정 ID','일시(UTC)']] + [[names[a['project_id']],a['message'],a['actor_name'] or '기록 없음 (기존 데이터)',a['actor_username'],a['created_at']] for a in activity])]
    filename = export_filename(projects[0]['name'] if project_id else '전체프로젝트', scope)
    return StreamingResponse(io.BytesIO(workbook(sheets)), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': f"attachment; filename=project-hub.xlsx; filename*=UTF-8''{quote(filename)}"})

class ImportProjectRow(BaseModel):
    sheet: str = Field(default='개요', max_length=30)
    row: int = Field(ge=2, le=100000)
    id: str | None = Field(default=None, max_length=100)
    data: dict = Field(max_length=15)

class ImportItemRow(BaseModel):
    sheet: Literal['일정', '3rd-party', '개발사']
    row: int = Field(ge=2, le=100000)
    id: str | None = Field(default=None, max_length=100)
    project_id: str | None = Field(default=None, max_length=100)
    project_name: str = Field(default='', max_length=160)
    data: dict = Field(max_length=20)

class ImportBatch(BaseModel):
    project_id: str | None = Field(default=None, max_length=100)
    projects: list[ImportProjectRow] = Field(default_factory=list, max_length=1000)
    items: list[ImportItemRow] = Field(default_factory=list, max_length=2000)
    ignored_sheets: list[str] = Field(default_factory=list, max_length=10)
    revision: str | None = Field(default=None, max_length=64)

    @model_validator(mode='after')
    def limit(self):
        if not 1 <= len(self.projects) + len(self.items) <= 2000:
            raise ValueError('가져올 데이터는 1~2,000행이어야 합니다.')
        return self

def import_snapshot(con):
    data = {t: [dict(r) for r in con.execute(f'SELECT * FROM {t} ORDER BY id')] for t in ['projects', 'items']}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

def plan_excel_import(con, batch):
    from pydantic import ValidationError
    projects = {p['id']: dict(p) for p in con.execute('SELECT * FROM projects')}
    items = {x['id']: dict(x) for x in con.execute('SELECT * FROM items')}
    if batch.project_id:
        require_project(con, batch.project_id)
    plans, changes, errors = [], [], []
    used_projects, used_items = set(), set()
    counts = {k: {'create': 0, 'update': 0, 'unchanged': 0} for k in ['project','schedule','third_party','developer']}
    def fail(row, message):
        errors.append({'msg': f'{row.sheet} {row.row}행: {message}', 'sheet': row.sheet, 'row': row.row})
    def summary(row, kind, identifier, fields, old):
        action = 'create' if old is None else ('unchanged' if all(old.get(k) == v for k,v in fields.items()) else 'update')
        counts[kind][action] += 1
        changes.append({'sheet': row.sheet, 'row': row.row, 'kind': kind, 'name': fields.get('name', fields.get('title','')), 'action': action})
        if action != 'unchanged':
            plans.append({'kind': kind, 'id': identifier, 'fields': fields, 'old': old, 'action': action})
    def error_text(exc):
        if isinstance(exc, ValidationError):
            return '; '.join(e['msg'].replace('Value error, ', '') for e in exc.errors()[:3])
        return str(exc)
    for row in batch.projects:
        try:
            if row.id:
                if row.id not in projects:
                    raise ValueError('원본 프로젝트를 찾을 수 없습니다. 새 프로젝트는 새 행에 작성하세요.')
                identifier = row.id
            elif batch.project_id:
                identifier = batch.project_id
            else:
                matches = [p['id'] for p in projects.values() if row.data.get('name') and p['name'] == row.data.get('name')]
                if len(matches) > 1:
                    raise ValueError('동일한 프로젝트명이 여러 개입니다. 최신 양식을 내려받아 수정하세요.')
                identifier = matches[0] if matches else secrets.token_hex(12)
            if batch.project_id and identifier != batch.project_id:
                raise ValueError('현재 프로젝트 이외의 내용은 반영할 수 없습니다.')
            if identifier in used_projects:
                raise ValueError('같은 프로젝트가 여러 행에 중복되어 있습니다.')
            old = projects.get(identifier)
            fields = Project.model_validate({**({'color': old['color']} if old else {}), **row.data}, context={'excel_import': True}).model_dump(mode='json')
            fields['start'] = fields['start'] or ''
            fields['end'] = fields['end'] or ''
            used_projects.add(identifier)
            summary(row, 'project', identifier, fields, old)
            projects[identifier] = {**(old or {}), 'id': identifier, **fields}
        except (ValueError, TypeError) as exc:
            fail(row, error_text(exc))
    for row in batch.items:
        try:
            old = items.get(row.id) if row.id else None
            if row.id and old is None:
                raise ValueError('원본 항목을 찾을 수 없습니다. 새 항목은 새 행에 작성하세요.')
            pid = row.project_id or (old['project_id'] if old else None) or batch.project_id
            if pid:
                if pid not in projects:
                    raise ValueError('프로젝트를 찾을 수 없습니다.')
                if batch.project_id and pid != batch.project_id:
                    raise ValueError('현재 프로젝트 이외의 내용은 반영할 수 없습니다.')
            else:
                matches = [p['id'] for p in projects.values() if p['name'] == row.project_name]
                if len(matches) != 1:
                    raise ValueError('프로젝트명을 확인하세요. 신규 프로젝트는 개요 시트에도 작성하세요.')
                pid = matches[0]
            if row.project_name and row.project_name != projects[pid]['name']:
                original = con.execute('SELECT name FROM projects WHERE id=?', (pid,)).fetchone()
                if not original or original['name'] != row.project_name:
                    raise ValueError('행의 프로젝트명이 원본 프로젝트와 다릅니다.')
            kind = row.data.get('kind')
            if kind not in ['schedule','third_party','developer'] or (row.sheet == '3rd-party' and kind != 'third_party') or (row.sheet == '개발사' and kind != 'developer'):
                raise ValueError('시트와 항목 유형이 일치하지 않습니다.')
            if old and (old['project_id'] != pid or old['kind'] != kind):
                raise ValueError('기존 항목의 프로젝트와 유형은 변경할 수 없습니다.')
            if old is None:
                matches = [x for x in items.values() if row.data.get('title') and x['project_id'] == pid and x['kind'] == kind and x['title'] == row.data.get('title') and (kind != 'developer' or x['vendor'] == row.data.get('vendor',''))]
                if len(matches) > 1:
                    raise ValueError('동일한 이름의 항목이 여러 개입니다. 최신 양식을 내려받아 수정하세요.')
                old = matches[0] if matches else None
            identifier = old['id'] if old else secrets.token_hex(12)
            if identifier in used_items:
                raise ValueError('같은 항목이 여러 행에 중복되어 있습니다.')
            base = {k: old[k] for k in Item.model_fields if k in old} if old else {}
            if old:
                base['checklist'] = json.loads(old['checklist'])
                for key in ['start','end','installed_at']:
                    base[key] = base[key] or None
            payload = {**base, **row.data}
            if kind == 'third_party':
                payload['progress'] = 0
                if 'checklist' in row.data:
                    existing = json.loads(old['checklist']) if old else []
                    taken = set()
                    reconciled = []
                    if not isinstance(row.data['checklist'], list):
                        raise ValueError('진행사항은 목록으로 입력하세요.')
                    for idx, entry in enumerate(row.data['checklist']):
                        match = next((t for t in existing if t['id'] not in taken and t['text'] == entry.get('text')), None)
                        if match is None and idx < len(existing) and existing[idx]['id'] not in taken:
                            match = existing[idx]
                        cid = match['id'] if match else secrets.token_hex(12)
                        taken.add(cid)
                        reconciled.append({'id': cid, 'text': entry.get('text',''), 'done': entry.get('done',False)})
                    payload['checklist'] = reconciled
            fields = {'project_id': pid, **item_fields(Item.model_validate(payload, context={'excel_import': True}))}
            used_items.add(identifier)
            summary(row, kind, identifier, fields, old)
            items[identifier] = {**(old or {}), 'id': identifier, **fields}
        except (ValueError, TypeError, AttributeError) as exc:
            fail(row, error_text(exc))
    if errors:
        raise HTTPException(422, errors[:100])
    return {'counts': counts, 'changes': changes, 'ignored_sheets': batch.ignored_sheets, 'revision': import_snapshot(con)}, plans

@app.post('/api/import/preview', dependencies=[Depends(auth)])
def preview_import(batch: ImportBatch):
    with db() as con:
        con.execute('BEGIN')
        summary, _ = plan_excel_import(con, batch)
    return summary

@app.post('/api/import/commit', dependencies=[Depends(auth)])
def commit_import(batch: ImportBatch, actor=Depends(auth)):
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        if not batch.revision or not hmac.compare_digest(batch.revision, import_snapshot(con)):
            raise HTTPException(409, '미리보기 이후 데이터가 변경되었습니다. 파일을 다시 선택해 확인하세요.')
        summary, plans = plan_excel_import(con, batch)
        for plan in plans:
            fields = plan['fields']
            table = 'projects' if plan['kind'] == 'project' else 'items'
            if plan['action'] == 'create':
                values = {'id': plan['id'], **fields, ('created_at' if table == 'projects' else 'updated_at'): now()}
                con.execute('INSERT INTO ' + table + ' (' + ','.join(values) + ') VALUES (' + ','.join('?' for _ in values) + ')', tuple(values.values()))
            else:
                values = dict(fields)
                if table == 'items':
                    values['updated_at'] = now()
                con.execute('UPDATE ' + table + ' SET ' + ','.join(k+'=?' for k in values) + ' WHERE id=?', (*values.values(), plan['id']))
            pid = plan['id'] if table == 'projects' else fields['project_id']
            label = {'project':'프로젝트','schedule':'일정','third_party':'3rd-party','developer':'개발사'}[plan['kind']]
            record(con, pid, f'Excel 가져오기 · {label} {"추가" if plan["action"] == "create" else "수정"} · {fields.get("name",fields.get("title",""))}', actor)
    return {'ok': True, **summary}
