import io, os, sqlite3, subprocess, sys, tempfile, unittest
from pathlib import Path
os.environ.update(APP_PASSWORD='Test-password-only-987!',SESSION_SECRET='test-session-secret-'*4,COOKIE_SECURE='false')
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from app import main

class AppTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();main.DB_PATH=str(Path(self.tmp.name)/'test.db');main.login_attempts.clear()
  self.client=TestClient(main.app);self.client.__enter__();self.h={'X-Requested-With':'ProjectHub'}
  self.client.post('/api/login',json={'username':'admin','password':os.environ['APP_PASSWORD']})
 def tearDown(self):
  self.client.__exit__(None,None,None);self.tmp.cleanup()
 def project(self,name='테스트 프로젝트'):
  b=dict(name=name,client='고객사',owner='김담당',start='2026-11-01',end='2026-12-31',status='진행 중',description='첫 줄\n둘째 줄')
  r=self.client.post('/api/projects',json=b,headers=self.h);self.assertEqual(r.status_code,201,r.text)
  return r.json()['id'],b
 def item(self,pid,**updates):
  b=dict(kind='schedule',title='일정 테스트',owner='김담당',start='2026-11-01',end='2026-11-10',status='진행 중',progress=30,notes='진행 메모');b.update(updates)
  r=self.client.post(f'/api/projects/{pid}/items',json=b,headers=self.h);self.assertEqual(r.status_code,201,r.text)
  return r.json()['id'],b
 def test_auth_and_logout(self):
  self.assertEqual(TestClient(main.app).get('/api/data').status_code,401)
  self.assertEqual(self.client.get('/api/data').status_code,200)
  self.assertEqual(self.client.post('/api/logout',headers=self.h).status_code,200)
  self.assertEqual(self.client.get('/api/data').status_code,401)
 def test_bad_password_and_rate_limit(self):
  for _ in range(10):self.assertEqual(self.client.post('/api/login',json={'username':'admin','password':'bad'}).status_code,401)
  self.assertEqual(self.client.post('/api/login',json={'username':'admin','password':'bad'}).status_code,429)
 def test_secure_cookie_and_csrf(self):
  os.environ['COOKIE_SECURE']='true'
  try:
   r=TestClient(main.app).post('/api/login',json={'username':'admin','password':os.environ['APP_PASSWORD']})
   for s in ['Secure','HttpOnly','SameSite=strict']:self.assertIn(s,r.headers['set-cookie'])
  finally:os.environ['COOKIE_SECURE']='false'
  self.assertEqual(self.client.post('/api/projects',json={}).status_code,403)
 def test_forged_cookie(self):
  self.client.cookies.set('ph_session','99999999999.invalid')
  self.assertEqual(self.client.get('/api/data').status_code,401)
 def test_project_edit_and_persistence(self):
  pid,b=self.project();b['name']='변경된 프로젝트'
  self.assertEqual(self.client.put('/api/projects/'+pid,json=b,headers=self.h).status_code,200)
  main.init_db()
  self.assertEqual(self.client.get('/api/data').json()['projects'][0]['name'],b['name'])
  with sqlite3.connect(main.DB_PATH) as c:self.assertEqual(c.execute('SELECT name FROM projects WHERE id=?',(pid,)).fetchone()[0],b['name'])
 def test_item_edit_completion_and_delete(self):
  pid,_=self.project();iid,b=self.item(pid);b['status']='완료'
  self.assertEqual(self.client.put('/api/items/'+iid,json=b,headers=self.h).status_code,200)
  data=self.client.get('/api/data').json();self.assertEqual(data['items'][0]['progress'],100);self.assertEqual(len(data['activity']),3)
  self.assertEqual(self.client.delete('/api/items/'+iid,headers=self.h).status_code,200)
  self.assertEqual(self.client.get('/api/data').json()['items'],[])
 def test_validation(self):
  pid,b=self.project();b['end']='2026-01-01'
  self.assertEqual(self.client.put('/api/projects/'+pid,json=b,headers=self.h).status_code,422)
  _,item=self.item(pid)
  for upd in [{'progress':101},{'progress':100},{'end':'2025-01-01'},{'kind':'developer','vendor':''},{'status':'unknown'},{'title':' '}]:
   self.assertEqual(self.client.post(f'/api/projects/{pid}/items',json={**item,**upd},headers=self.h).status_code,422)
 def test_cascade_delete(self):
  pid,_=self.project();self.item(pid,kind='developer',vendor='파트너')
  self.client.delete('/api/projects/'+pid,headers=self.h)
  self.assertEqual(self.client.get('/api/data').json(),dict(projects=[],items=[],activity=[]))
  self.assertEqual(self.client.get('/api/export.xlsx?project_id='+pid).status_code,404)
 def test_export_types_filter_and_formula_safety(self):
  p1,_=self.project('프로젝트 A');p2,_=self.project('프로젝트 B')
  self.item(p1,title='=HYPERLINK("https://example.com")',kind='developer',vendor='파트너 A',progress=35);self.item(p2,title='별도 업무')
  r=self.client.get('/api/export.xlsx?project_id='+p1);self.assertEqual(r.status_code,200);self.assertIn('attachment',r.headers['content-disposition'])
  w=load_workbook(io.BytesIO(r.content));self.assertEqual(w.sheetnames,['개요','일정','3rd-party','개발사','변경이력'])
  self.assertEqual(w['개요'].max_row,2);self.assertEqual(w['일정'].max_row,1)
  s=w['개발사'];self.assertEqual(s['B2'].data_type,'s');self.assertTrue(s['B2'].value.startswith('=HYPERLINK'))
  self.assertEqual(s['I2'].value,.35);self.assertEqual(s['I2'].number_format,'0%');self.assertEqual(s['E2'].value.year,2026)
  self.assertEqual(s.freeze_panes,'A2');self.assertEqual(s.auto_filter.ref,'A1:K2')
  self.assertEqual(self.client.get('/api/export.xlsx').status_code,422)
 def test_empty_export_health_and_page(self):
  self.assertTrue(all(s.max_row==1 for s in load_workbook(io.BytesIO(self.client.get('/api/export.xlsx?scope=calendar').content))))
  for url in ['/healthz','/readyz','/']:self.assertEqual(self.client.get(url).status_code,200)
  self.assertIn('frame-ancestors',self.client.get('/').headers['content-security-policy'])
 def test_backup(self):
  self.project();dest=Path(self.tmp.name)/'backup.db'
  subprocess.run([sys.executable,'scripts/backup.py',str(dest)],env={**os.environ,'DB_PATH':main.DB_PATH},check=True,capture_output=True)
  with sqlite3.connect(dest) as c:
   self.assertEqual(c.execute('SELECT COUNT(*) FROM projects').fetchone()[0],1);self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
 def test_missing_records(self):
  for path in ['/api/items/missing','/api/projects/missing']:self.assertEqual(self.client.delete(path,headers=self.h).status_code,404)
  self.assertEqual(self.client.get('/api/export.xlsx?project_id=missing').status_code,404)
 def test_export_screen_scopes_and_project_isolation(self):
  p1,_=self.project('고객 A');p2,_=self.project('고객 B')
  self.item(p1,title='A 일정');self.item(p1,kind='developer',vendor='A 업체',title='A 요청')
  self.item(p2,kind='developer',vendor='B 업체',title='B 요청')
  def book(query):
   r=self.client.get('/api/export.xlsx?'+query);self.assertEqual(r.status_code,200,r.text)
   return load_workbook(io.BytesIO(r.content))
  w=book('scope=calendar');self.assertEqual(w.sheetnames,['일정']);self.assertEqual(w.active.max_row,4)
  self.assertEqual(w.active['B1'].value,'유형')
  w=book('scope=project&project_id='+p1);self.assertEqual(len(w.sheetnames),5)
  self.assertEqual(w['개요'].max_row,2);self.assertEqual(w['개발사'].max_row,2)
  self.assertNotIn('고객 B',str(list(w['개요'].values)))
  w=book('scope=developer&project_id='+p1);self.assertEqual(w.sheetnames,['개발사'])
  self.assertEqual(w.active.max_row,2);self.assertEqual(w.active['B2'].value,'A 요청')
  self.assertNotIn('A 일정',str(list(w.active.values)));self.assertNotIn('B 요청',str(list(w.active.values)))
  self.assertEqual(self.client.get('/api/export.xlsx?scope=project').status_code,422)
  self.assertEqual(self.client.get('/api/export.xlsx?scope=all').status_code,422)
 def test_account_actor_cannot_be_forged(self):
  with main.db() as c:
   c.execute('INSERT INTO users(id,username,name,password_hash) VALUES(?,?,?,?)',('u2','reviewer','검토 담당자',main.hash_password('Reviewer-Password-2026!')))
  pid,b=self.project();b['name']='검토 완료';b['actor_name']='위조 이름'
  other=TestClient(main.app)
  self.assertEqual(other.post('/api/login',json={'username':'reviewer','password':'Reviewer-Password-2026!'}).status_code,200)
  self.assertEqual(other.get('/api/me').json()['name'],'검토 담당자')
  self.assertEqual(other.put('/api/projects/'+pid,json=b,headers=self.h).status_code,200)
  logs=self.client.get('/api/data').json()['activity']
  self.assertEqual(logs[0]['actor_name'],'검토 담당자');self.assertEqual(logs[0]['actor_username'],'reviewer');self.assertEqual(logs[0]['actor_id'],'u2')
  self.assertEqual(logs[1]['actor_name'],'관리자');self.assertEqual(logs[1]['actor_username'],'admin')
  with main.db() as c:c.execute("UPDATE users SET name='새 이름' WHERE id='u2'")
  self.assertEqual(self.client.get('/api/data').json()['activity'][0]['actor_name'],'검토 담당자')
  w=load_workbook(io.BytesIO(self.client.get('/api/export.xlsx?project_id='+pid).content))
  self.assertEqual(w['변경이력']['C2'].value,'검토 담당자');self.assertEqual(w['변경이력']['D2'].value,'reviewer')
  with main.db() as c:c.execute("UPDATE users SET active=0 WHERE id='u2'")
  self.assertEqual(other.get('/api/me').status_code,401)
 def test_legacy_migration_preserves_records(self):
  pid,_=self.project()
  with main.db() as c:
   c.execute('DROP TABLE activity')
   c.execute('CREATE TABLE activity(id INTEGER PRIMARY KEY AUTOINCREMENT,project_id TEXT NOT NULL,message TEXT NOT NULL,created_at TEXT NOT NULL)')
   c.execute('INSERT INTO activity(project_id,message,created_at) VALUES(?,?,?)',(pid,'이전 기록',main.now()))
  main.init_db()
  a=self.client.get('/api/data').json()['activity'][0]
  self.assertEqual(a['message'],'이전 기록');self.assertEqual(a['actor_name'],'')
  with main.db() as c:
   self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],8)
   self.assertEqual(c.execute('SELECT COUNT(*) FROM users').fetchone()[0],1)
 def third_party(self,pid,**updates):
  b=dict(kind='third_party',title='모니터링 에이전트',installed_at='2026-11-03',developer_applied=False,priority='높음',progress=40,owner='설치 담당',notes='적용 테스트 예정',checklist=[{'id':'step1','text':'패키지 설치','done':False},{'id':'step2','text':'개발사 적용 테스트','done':False}]);b.update(updates)
  r=self.client.post(f'/api/projects/{pid}/items',json=b,headers=self.h);self.assertEqual(r.status_code,201,r.text)
  return r.json()['id'],b
 def test_third_party_checklist_and_application_are_independent(self):
  pid,_=self.project();iid,b=self.third_party(pid)
  for cid in ['step2','step1']:
   self.assertEqual(self.client.patch(f'/api/items/{iid}/checklist/{cid}',json={'done':True},headers=self.h).status_code,200)
  self.assertEqual(self.client.patch(f'/api/items/{iid}/application',json={'done':True},headers=self.h).status_code,200)
  x=self.client.get('/api/data').json()['items'][0]
  self.assertTrue(all(t['done'] for t in x['checklist']));self.assertTrue(x['developer_applied']);self.assertEqual(x['progress'],14)
  self.client.patch(f'/api/items/{iid}/checklist/step1',json={'done':False},headers=self.h)
  x=self.client.get('/api/data').json()['items'][0]
  self.assertFalse(x['checklist'][0]['done']);self.assertTrue(x['checklist'][1]['done']);self.assertTrue(x['developer_applied'])
  a=self.client.get('/api/data').json()['activity'][0];self.assertEqual(a['actor_username'],'admin');self.assertIn('완료 취소',a['message'])
  self.assertEqual(self.client.patch(f'/api/items/{iid}/checklist/missing',json={'done':True},headers=self.h).status_code,404)
  self.assertEqual(TestClient(main.app).patch(f'/api/items/{iid}/application',json={'done':True},headers=self.h).status_code,401)
 def test_third_party_export_alignment_names_and_rich_strike(self):
  pid,_=self.project('프로젝트: A/테스트');iid,b=self.third_party(pid)
  self.item(pid,kind='developer',vendor='개발사 A',title='개발 반영');self.item(pid,title='일정')
  self.client.patch(f'/api/items/{iid}/checklist/step1',json={'done':True},headers=self.h)
  r=self.client.get('/api/export.xlsx?project_id='+pid)
  self.assertIn("filename*=UTF-8''",r.headers['content-disposition'])
  from urllib.parse import unquote
  filename=unquote(r.headers['content-disposition'].split("filename*=UTF-8''")[1])
  self.assertTrue(filename.startswith('프로젝트_ A_테스트_프로젝트_'))
  w=load_workbook(io.BytesIO(r.content));self.assertEqual(w.sheetnames,['개요','일정','3rd-party','개발사','변경이력'])
  s=w['3rd-party'];self.assertEqual(s['C2'].value.year,2026);self.assertEqual(s['O2'].value,0)
  self.assertIn('● 패키지 설치',s['Q2'].value);self.assertIn('○ 개발사 적용 테스트',s['Q2'].value)
  for sheet in w:
   for row in sheet:
    for cell in row:self.assertEqual(cell.alignment.vertical,'top',(sheet.title,cell.coordinate))
  import zipfile,xml.etree.ElementTree as ET
  with zipfile.ZipFile(io.BytesIO(r.content)) as z:
   root=ET.fromstring(z.read('xl/worksheets/sheet3.xml'));ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
   runs=root.findall('.//m:c[@r="Q2"]/m:is/m:r',ns)
   self.assertIsNotNone(runs[0].find('m:rPr/m:strike',ns));self.assertIsNone(runs[1].find('m:rPr/m:strike',ns))
  third=load_workbook(io.BytesIO(self.client.get('/api/export.xlsx?scope=third_party&project_id='+pid).content))
  self.assertEqual(third.sheetnames,['3rd-party']);self.assertEqual(third.active.max_row,2)
 def test_third_party_without_installation_and_duplicate_checks(self):
  pid,_=self.project();iid,b=self.third_party(pid,installed_at=None)
  w=load_workbook(io.BytesIO(self.client.get('/api/export.xlsx?scope=calendar').content));self.assertEqual(w.active.max_row,1)
  b['checklist']=[{'id':'same','text':'A'},{'id':'same','text':'B'}]
  self.assertEqual(self.client.put('/api/items/'+iid,json=b,headers=self.h).status_code,422)
 def test_legacy_partner_migrates_once_without_losing_notes(self):
  pid,_=self.project()
  with main.db() as c:
   c.execute('INSERT INTO items(id,project_id,kind,title,vendor,owner,start,end,status,priority,progress,notes,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',('old-partner',pid,'partner','기존 요청','기존 업체','담당자','2026-11-01','2026-11-03','진행 중','높음',30,'보관할 메모',main.now()))
  main.init_db();main.init_db()
  x=self.client.get('/api/data').json()['items'][0]
  self.assertEqual(x['id'],'old-partner');self.assertEqual(x['kind'],'third_party');self.assertEqual(x['title'],'기존 업체')
  self.assertIn('기존 요청',x['checklist'][0]['text']);self.assertEqual(x['notes'],'보관할 메모');self.assertEqual(len(x['checklist']),1)
 def test_third_party_default_steps_and_automatic_rounding(self):
  pid,_=self.project()
  r=self.client.post(f'/api/projects/{pid}/items',json={'kind':'third_party','title':'기본 목록 검증'},headers=self.h)
  self.assertEqual(r.status_code,201,r.text);iid=r.json()['id']
  def current():return next(x for x in self.client.get('/api/data').json()['items'] if x['id']==iid)
  x=current();self.assertEqual(x['checklist'],[]);self.assertEqual([t['text'] for t in x['progress_steps']],main.DEFAULT_THIRD_PARTY_STEPS)
  self.assertEqual(len(x['progress_steps']),7);self.assertEqual(x['progress'],0);self.assertTrue(all(not t['done'] for t in x['progress_steps']))
  for count,t in enumerate(x['progress_steps'],1):
   self.client.patch(f'/api/items/{iid}/progress-steps/'+t['id'],json={'done':True},headers=self.h)
   self.assertEqual(current()['progress'],[14,29,43,57,71,86,100][count-1])
  self.assertEqual(current()['status'],'완료')
  self.client.patch(f'/api/items/{iid}/progress-steps/'+x['progress_steps'][0]['id'],json={'done':False},headers=self.h)
  self.assertEqual(current()['progress'],86);self.assertEqual(current()['status'],'진행 중')
 def test_third_party_edit_add_remove_and_empty_list_recalculate(self):
  pid,_=self.project();iid,b=self.third_party(pid,progress=99,checklist=[{'id':'1','text':'완료 항목','done':True},{'id':'2','text':'남은 항목','done':False},{'id':'3','text':'추가 점검','done':False}])
  def current():return self.client.get('/api/data').json()['items'][0]
  self.assertEqual(current()['progress'],0)
  b['checklist'].pop();b['checklist'][0]['text']='완료 내용 수정';b['progress']=0
  self.assertEqual(self.client.put('/api/items/'+iid,json=b,headers=self.h).status_code,200)
  self.assertEqual(current()['progress'],0);self.assertEqual(current()['checklist'][0]['text'],'완료 내용 수정')
  w=load_workbook(io.BytesIO(self.client.get('/api/export.xlsx?scope=third_party&project_id='+pid).content))
  self.assertEqual(w['3rd-party']['O2'].value,0)
  b['checklist']=[{'id':'remaining','text':'최종 확인','done':False}]
  self.client.put('/api/items/'+iid,json=b,headers=self.h);self.assertEqual(current()['progress'],0)
  b['checklist']=[];self.client.put('/api/items/'+iid,json=b,headers=self.h)
  main.init_db();self.assertEqual(current()['checklist'],[]);self.assertEqual(current()['progress'],0)
  self.assertEqual(current()['status'],'예정')
 def test_existing_checklist_preserved_when_progress_is_recalculated(self):
  pid,_=self.project();iid,_=self.third_party(pid)
  with main.db() as c:c.execute("UPDATE items SET progress=90,status='진행 중' WHERE id=?",(iid,))
  main.init_db()
  x=self.client.get('/api/data').json()['items'][0]
  self.assertEqual([t['id'] for t in x['checklist']],['step1','step2']);self.assertEqual(x['progress'],0)
 def test_project_color_create_edit_persistence_and_validation(self):
  pid,b=self.project('기본 색상')
  self.assertEqual(self.client.get('/api/data').json()['projects'][0]['color'],'#4f8064')
  b['name']='파랑 프로젝트';b['color']='#3976C4'
  r=self.client.post('/api/projects',json=b,headers=self.h);self.assertEqual(r.status_code,201,r.text);blue=r.json()['id']
  def color(pid):return next(p['color'] for p in self.client.get('/api/data').json()['projects'] if p['id']==pid)
  self.assertEqual(color(blue),'#3976c4');self.assertEqual(color(pid),'#4f8064')
  b['color']='#855CBA';self.assertEqual(self.client.put('/api/projects/'+blue,json=b,headers=self.h).status_code,200)
  main.init_db();self.assertEqual(color(blue),'#855cba')
  for invalid in ['red','#123','#12345678','#zzzzzz','url(https://example.com)','red;display:none']:
   self.assertEqual(self.client.put('/api/projects/'+blue,json={**b,'color':invalid},headers=self.h).status_code,422)
  self.assertEqual(color(blue),'#855cba')
 def test_project_color_legacy_migration_preserves_project_and_items(self):
  pid,_=self.project();iid,_=self.item(pid)
  with main.db() as c:
   c.execute('ALTER TABLE projects DROP COLUMN color')
   c.execute('PRAGMA user_version=3')
  main.init_db()
  data=self.client.get('/api/data').json()
  self.assertEqual(data['projects'][0]['id'],pid);self.assertEqual(data['projects'][0]['color'],'#4f8064')
  self.assertEqual(data['items'][0]['id'],iid);self.assertEqual(data['items'][0]['project_id'],pid)
 def import_preview(self,batch):
  r=self.client.post('/api/import/preview',json=batch,headers=self.h);self.assertEqual(r.status_code,200,r.text);return {**batch,'revision':r.json()['revision']},r.json()
 def test_import_preview_atomic_commit_and_actor(self):
  batch={'projects':[{'row':2,'data':dict(name='엑셀 신규',start='2026-11-01',end='2026-12-01')}], 'items':[{'sheet':'3rd-party','row':2,'project_name':'엑셀 신규','data':dict(kind='third_party',title='솔루션 A',checklist=[dict(id='x',text='수신',done=True),dict(id='y',text='설치',done=False)],progress=99)}],'ignored_sheets':['변경이력']}
  commit,summary=self.import_preview(batch);self.assertEqual(summary['counts']['project']['create'],1);self.assertEqual(len(self.client.get('/api/data').json()['projects']),0)
  r=self.client.post('/api/import/commit',json=commit,headers=self.h);self.assertEqual(r.status_code,200,r.text)
  data=self.client.get('/api/data').json();self.assertEqual(data['items'][0]['progress'],0);self.assertEqual(len(data['activity']),2);self.assertTrue(all(x['actor_username']=='admin' for x in data['activity']))
 def test_import_invalid_batch_and_scope(self):
  pid,_=self.project();other,_=self.project('다른 프로젝트')
  batch={'project_id':pid,'projects':[],'items':[{'sheet':'일정','row':2,'project_id':pid,'data':dict(kind='schedule',title='유효',start='2026-11-01',end='2026-11-05')},{'sheet':'일정','row':3,'project_id':other,'data':dict(kind='schedule',title='불가',start='2026-11-01',end='2026-11-05')}]}
  r=self.client.post('/api/import/preview',json=batch,headers=self.h);self.assertEqual(r.status_code,422,r.text);self.assertIn('3행',r.text);self.assertEqual(self.client.get('/api/data').json()['items'],[])
  batch['items'][1]['project_id']=pid;batch['items'][1]['data']['end']='2026-10-01';r=self.client.post('/api/import/preview',json=batch,headers=self.h);self.assertEqual(r.status_code,422);self.assertEqual(self.client.get('/api/data').json()['items'],[])
 def test_import_stale_preview_rejected(self):
  pid,_=self.project();batch={'projects':[],'items':[{'sheet':'일정','row':2,'project_id':pid,'data':dict(kind='schedule',title='새 업무',start='2026-11-01',end='2026-11-05')}]}
  commit,_=self.import_preview(batch);self.item(pid);r=self.client.post('/api/import/commit',json=commit,headers=self.h);self.assertEqual(r.status_code,409);self.assertEqual(len(self.client.get('/api/data').json()['items']),1)
 def test_import_existing_ids_and_legacy_matching(self):
  pid,p=self.project();iid,b=self.item(pid,kind='third_party',title='솔루션',checklist=[dict(id='keep-id',text='기존 항목',done=False)])
  batch={'project_id':pid,'projects':[{'row':2,'id':pid,'data':{**p,'name':'새 이름'}}],'items':[{'sheet':'3rd-party','row':2,'id':iid,'project_id':pid,'project_name':p['name'],'data':dict(kind='third_party',title='변경 솔루션',checklist=[dict(id='excel-0',text='기존 항목',done=True)])}]}
  commit,_=self.import_preview(batch);r=self.client.post('/api/import/commit',json=commit,headers=self.h);self.assertEqual(r.status_code,200,r.text);data=self.client.get('/api/data').json();self.assertEqual(data['items'][0]['id'],iid);self.assertEqual(data['items'][0]['checklist'][0]['id'],'keep-id');self.assertEqual(data['projects'][0]['color'],'#4f8064')
  batch['projects']=[];batch['items'][0]['id']=None;batch['items'][0]['project_name']='새 이름';batch['items'][0]['data']['title']='변경 솔루션';_,summary=self.import_preview(batch);self.assertEqual(summary['counts']['third_party']['unchanged'],1)
 def test_import_export_roundtrip_unchanged(self):
  pid,p=self.project();self.item(pid);self.item(pid,kind='third_party',title='솔루션',checklist=[dict(id='stable',text='확인',done=True)])
  data=self.client.get('/api/data').json();project=data['projects'][0];batch={'project_id':pid,'projects':[{'row':2,'id':pid,'data':{k:project[k] for k in main.Project.model_fields if k!='color'}}],'items':[]}
  for i,x in enumerate(data['items']):batch['items'].append({'sheet':'3rd-party' if x['kind']=='third_party' else '일정','row':i+2,'id':x['id'],'project_id':pid,'data':{k:(x[k] or None) if k in ['start','end','installed_at','license_expires_at'] else x[k] for k in main.Item.model_fields}})
  _,summary=self.import_preview(batch);self.assertTrue(all(c['update']==0 and c['create']==0 for c in summary['counts'].values()))
  wb=load_workbook(io.BytesIO(self.client.get('/api/export.xlsx',params={'scope':'project','project_id':pid}).content));self.assertTrue(wb['3rd-party'].column_dimensions['T'].hidden);self.assertIn('● 확인',wb['3rd-party']['Q2'].value)
 def test_import_duplicate_row_rejected(self):
  pid,_=self.project();iid,b=self.item(pid);row={'sheet':'일정','row':2,'id':iid,'project_id':pid,'data':b};r=self.client.post('/api/import/preview',json={'projects':[],'items':[row,{**row,'row':3}]},headers=self.h);self.assertEqual(r.status_code,422);self.assertIn('중복',r.text)

 def test_developer_dates_are_optional_in_ui_api(self):
  pid,_=self.project();iid,b=self.item(pid,kind='developer',vendor='개발사',start=None,end=None)
  b['start']='2026-11-09';r=self.client.put('/api/items/'+iid,json=b,headers=self.h);self.assertEqual(r.status_code,200,r.text)
  b['end']='2026-11-01';self.assertEqual(self.client.put('/api/items/'+iid,json=b,headers=self.h).status_code,422)
  b.update(start=None,end=None,vendor='');self.assertEqual(self.client.put('/api/items/'+iid,json=b,headers=self.h).status_code,422)
 def test_import_missing_required_values_then_strict_edit(self):
  batch={'projects':[{'row':2,'data':{'name':'','start':None,'end':None}}],'items':[]}
  commit,_=self.import_preview(batch);r=self.client.post('/api/import/commit',json=commit,headers=self.h);self.assertEqual(r.status_code,200,r.text)
  data=self.client.get('/api/data').json();pid=data['projects'][0]['id'];self.assertEqual(data['projects'][0]['name'],'');self.assertEqual(data['projects'][0]['start'],'')
  self.assertEqual(self.client.put('/api/projects/'+pid,json={'name':'','start':None,'end':None},headers=self.h).status_code,422)
  batch={'project_id':pid,'projects':[],'items':[{'sheet':sheet,'row':2,'data':{'kind':kind,'title':'','start':None,'end':None,'vendor':''}} for sheet,kind in [('일정','schedule'),('개발사','developer'),('3rd-party','third_party')]]}
  commit,_=self.import_preview(batch);r=self.client.post('/api/import/commit',json=commit,headers=self.h);self.assertEqual(r.status_code,200,r.text)
  data=self.client.get('/api/data').json();self.assertEqual(len(data['items']),3)
  for item in data['items']:
   body={k:(item[k] or None) if k in ['start','end','installed_at','license_expires_at'] else item[k] for k in main.Item.model_fields}
   self.assertEqual(self.client.put('/api/items/'+item['id'],json=body,headers=self.h).status_code,422)
   body['title']='보완한 업무'
   if item['kind']=='developer':body['vendor']='개발사'
   if item['kind']=='schedule':body.update(start='2026-11-01',end='2026-11-05')
   self.assertEqual(self.client.put('/api/items/'+item['id'],json=body,headers=self.h).status_code,200)
  self.assertEqual(self.client.get('/api/export.xlsx',params={'scope':'project','project_id':pid}).status_code,200)

 def test_license_fields_and_progress_sections(self):
  pid,_=self.project();iid,b=self.third_party(pid,license_type='임시',license_expires_at='2026-11-20')
  x=self.client.get('/api/data').json()['items'][0];self.assertEqual(x['license_type'],'임시');self.assertEqual(x['license_expires_at'],'2026-11-20');self.assertEqual(len(x['progress_steps']),7)
  self.client.patch(f'/api/items/{iid}/progress-steps/stage-0',json={'done':True},headers=self.h)
  self.client.patch(f'/api/items/{iid}/checklist/step1',json={'done':True},headers=self.h)
  x=self.client.get('/api/data').json()['items'][0];self.assertEqual(x['progress'],14);self.assertTrue(x['checklist'][0]['done'])
  body={k:x[k] for k in main.Item.model_fields};body.update(start=None,end=None,installed_at=None,license_perpetual=True)
  r=self.client.put('/api/items/'+iid,json=body,headers=self.h);self.assertEqual(r.status_code,200,r.text);x=self.client.get('/api/data').json()['items'][0];self.assertEqual(x['license_expires_at'],'');self.assertTrue(x['license_perpetual']);self.assertEqual(x['progress'],14)
  self.assertEqual(self.client.patch(f'/api/items/{iid}/progress-steps/invalid',json={'done':True},headers=self.h).status_code,404)
  body['progress_steps']=[];self.assertEqual(self.client.put('/api/items/'+iid,json=body,headers=self.h).status_code,200);main.init_db();self.assertEqual(self.client.get('/api/data').json()['items'][0]['progress_steps'],[])
 def test_legacy_defaults_move_to_progress_once(self):
  pid,_=self.project();iid,_=self.third_party(pid)
  tasks=[dict(id=str(i),text=t,done=True) for i,t in enumerate(main.LEGACY_THIRD_PARTY_STEPS)]
  with main.db() as c:
   c.execute('UPDATE items SET progress_steps=?,checklist=?,developer_applied=1 WHERE id=?',('[]',main.json.dumps(tasks,ensure_ascii=False),iid));c.execute('PRAGMA user_version=5')
  main.init_db();first=self.client.get('/api/data').json()['items'][0];main.init_db();second=self.client.get('/api/data').json()['items'][0]
  self.assertEqual(first['checklist'],[]);self.assertEqual(first['progress'],100);self.assertEqual(first['progress_steps'],second['progress_steps']);self.assertEqual(first['id'],iid)
 def test_license_and_milestone_excel_roundtrip(self):
  pid,_=self.project();stages=main.new_progress_steps();stages[0]['done']=True;stages[4]['done']=True
  iid,_=self.third_party(pid,progress_steps=stages,license_type='정식',license_expires_at='2026-12-20')
  w=load_workbook(io.BytesIO(self.client.get('/api/export.xlsx',params={'project_id':pid}).content));s=w['3rd-party'];headers={c.value:c.column for c in s[1]};self.assertEqual(s.cell(2,headers['라이선스 구분']).value,'정식');self.assertEqual(s.cell(2,headers['라이선스 만료일']).value.day,20);self.assertIn('● 개발사 적용 완료',s.cell(2,headers['진행사항']).value);self.assertIn('○ 패키지 설치',s.cell(2,headers['확인사항']).value)
  x=self.client.get('/api/data').json()['items'][0];body={k:(x[k] or None) if k in ['start','end','installed_at','license_expires_at'] else x[k] for k in main.Item.model_fields};batch={'project_id':pid,'items':[{'sheet':'3rd-party','row':2,'id':iid,'data':body}]};_,summary=self.import_preview(batch);self.assertEqual(summary['counts']['third_party']['unchanged'],1)

 def test_edit_progress_steps_add_remove_rename_and_restart(self):
  pid,_=self.project();iid,b=self.third_party(pid)
  b['progress_steps']=[dict(id='custom-a',text='수정된 진행 항목',done=True),dict(id='stage-4',text='개발 적용 검증',done=False)]
  r=self.client.put('/api/items/'+iid,json=b,headers=self.h);self.assertEqual(r.status_code,200,r.text)
  x=self.client.get('/api/data').json()['items'][0];self.assertEqual(x['progress'],50);self.assertEqual(x['progress_steps'][0]['text'],'수정된 진행 항목')
  self.client.patch('/api/items/'+iid+'/progress-steps/stage-4',json={'done':True},headers=self.h);x=self.client.get('/api/data').json()['items'][0];self.assertEqual(x['progress'],100);self.assertTrue(x['developer_applied'])
  b['progress_steps']=[dict(id='custom-a',text='최종 완료',done=True)]
  self.assertEqual(self.client.put('/api/items/'+iid,json=b,headers=self.h).status_code,200);main.init_db();x=self.client.get('/api/data').json()['items'][0];self.assertEqual(len(x['progress_steps']),1);self.assertEqual(x['progress'],100);self.assertFalse(x['developer_applied'])
  b['progress_steps']=[dict(id='dup',text='A'),dict(id='dup',text='B')];self.assertEqual(self.client.put('/api/items/'+iid,json=b,headers=self.h).status_code,422)
 def test_custom_progress_import_preserves_ids_and_empty_list(self):
  pid,_=self.project();iid,b=self.third_party(pid,progress_steps=[dict(id='my-stage',text='사용자 단계',done=False)])
  batch={'project_id':pid,'items':[{'sheet':'3rd-party','row':2,'id':iid,'data':{'kind':'third_party','title':b['title'],'progress_steps':[dict(id='excel-0',text='이름 변경',done=True)]}}]}
  commit,_=self.import_preview(batch);self.assertEqual(self.client.post('/api/import/commit',json=commit,headers=self.h).status_code,200);x=self.client.get('/api/data').json()['items'][0];self.assertEqual(x['progress_steps'][0]['id'],'my-stage');self.assertEqual(x['progress'],100)
  batch['items'][0]['data']['progress_steps']=[];commit,_=self.import_preview(batch);self.assertEqual(self.client.post('/api/import/commit',json=commit,headers=self.h).status_code,200);main.init_db();x=self.client.get('/api/data').json()['items'][0];self.assertEqual(x['progress_steps'],[]);self.assertEqual(x['progress'],0)

 def test_list_autosave_preserves_general_fields_and_audits_actor(self):
  pid,_=self.project();iid,b=self.third_party(pid,owner='원래 담당',notes='원래 메모',license_type='정식',license_expires_at='2026-12-05')
  stages=[dict(id='s1',text='자동 저장 단계',done=True),dict(id='stage-4',text='개발 적용',done=False)];checks=[dict(id='c1',text='확인 수정',done=True)]
  payload=dict(progress_steps=stages,checklist=checks,owner='덮어쓰면 안됨',notes='덮어쓰면 안됨')
  r=self.client.patch('/api/items/'+iid+'/lists',json=payload,headers=self.h);self.assertEqual(r.status_code,200,r.text);x=r.json();self.assertEqual(x['progress'],50);self.assertEqual(x['owner'],'원래 담당');self.assertEqual(x['notes'],'원래 메모');self.assertEqual(x['license_expires_at'],'2026-12-05');self.assertEqual(x['checklist'],checks)
  data=self.client.get('/api/data').json();count=len(data['activity']);self.assertEqual(data['activity'][0]['actor_username'],'admin');self.assertIn('자동 저장',data['activity'][0]['message'])
  self.client.patch('/api/items/'+iid+'/lists',json=payload,headers=self.h);self.assertEqual(len(self.client.get('/api/data').json()['activity']),count)
  stages[1]['done']=True;r=self.client.patch('/api/items/'+iid+'/lists',json=dict(progress_steps=stages,checklist=[]),headers=self.h);self.assertEqual(r.json()['progress'],100);self.assertTrue(r.json()['developer_applied']);self.assertEqual(r.json()['checklist'],[])
  self.client.patch('/api/items/'+iid+'/lists',json=dict(progress_steps=[],checklist=[]),headers=self.h);main.init_db();self.assertEqual(self.client.get('/api/data').json()['items'][0]['progress_steps'],[])
 def test_list_autosave_validation_auth_and_incomplete_import(self):
  pid,_=self.project();iid,_=self.item(pid)
  route='/api/items/'+iid+'/lists';payload={'progress_steps':[],'checklist':[]};self.assertEqual(self.client.patch(route,json=payload,headers=self.h).status_code,404);self.assertEqual(TestClient(main.app).patch(route,json=payload,headers=self.h).status_code,401)
  batch={'project_id':pid,'items':[{'sheet':'3rd-party','row':2,'data':{'kind':'third_party','title':''}}]};commit,_=self.import_preview(batch);self.client.post('/api/import/commit',json=commit,headers=self.h);x=next(x for x in self.client.get('/api/data').json()['items'] if x['kind']=='third_party');route='/api/items/'+x['id']+'/lists'
  r=self.client.patch(route,json={'progress_steps':[{'id':'test','text':'필수값 없는 항목에서도 저장','done':True}],'checklist':[]},headers=self.h);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['title'],'');self.assertEqual(r.json()['progress'],100)
  bad={'progress_steps':[{'id':'dup','text':'A'},{'id':'dup','text':'B'}],'checklist':[]};self.assertEqual(self.client.patch(route,json=bad,headers=self.h).status_code,422);self.assertEqual(self.client.patch(route,json=payload).status_code,403)

 def test_third_party_contacts_roundtrip_export_and_partial_save(self):
  pid,_=self.project();iid,b=self.third_party(pid,company_name='테스트 업체',sales_contact='영업 담당',engineer_contact='기술 담당')
  x=self.client.get('/api/data').json()['items'][0];self.assertEqual(x['owner'],'기술 담당')
  self.client.patch('/api/items/'+iid+'/lists',json={'progress_steps':[],'checklist':[],'company_name':'덮어쓰기 금지'},headers=self.h)
  x=self.client.get('/api/data').json()['items'][0];self.assertEqual(x['company_name'],'테스트 업체');self.assertEqual(x['sales_contact'],'영업 담당');self.assertEqual(x['engineer_contact'],'기술 담당')
  wb=load_workbook(io.BytesIO(self.client.get('/api/export.xlsx',params={'scope':'third_party','project_id':pid}).content));rows=list(wb.active.values);record=dict(zip(rows[0],rows[1]));self.assertEqual(record['업체명'],'테스트 업체');self.assertEqual(record['담당 영업 이름'],'영업 담당');self.assertEqual(record['담당 엔지니어 이름'],'기술 담당');self.assertNotIn('담당자',rows[0])
  batch={'project_id':pid,'items':[{'sheet':'3rd-party','row':2,'id':iid,'data':{'kind':'third_party','company_name':'새 업체','sales_contact':'새 영업','engineer_contact':''}}]};commit,_=self.import_preview(batch);r=self.client.post('/api/import/commit',json=commit,headers=self.h);self.assertEqual(r.status_code,200,r.text)
  main.init_db();x=self.client.get('/api/data').json()['items'][0];self.assertEqual(x['company_name'],'새 업체');self.assertEqual(x['sales_contact'],'새 영업');self.assertEqual(x['engineer_contact'],'');self.assertEqual(x['owner'],'')
 def test_contacts_migrate_old_owner_once(self):
  pid,_=self.project();iid,_=self.third_party(pid,owner='기존 담당자')
  with main.db() as con:
   for k in ['company_name','sales_contact','engineer_contact']:con.execute('ALTER TABLE items DROP COLUMN '+k)
   con.execute('PRAGMA user_version=6')
  main.init_db();x=self.client.get('/api/data').json()['items'][0];self.assertEqual(x['engineer_contact'],'기존 담당자');self.assertEqual(x['company_name'],'');self.assertEqual(x['sales_contact'],'')
  with main.db() as con:con.execute("UPDATE items SET engineer_contact='' WHERE id=?",(iid,))
  main.init_db();self.assertEqual(self.client.get('/api/data').json()['items'][0]['engineer_contact'],'')

 def test_sales_engineer_details_persist_export_import_and_autosave(self):
  pid,_=self.project();details={'sales_contact':'영업 이름','sales_phone':'010-0012-0034','sales_email':'sales@example.com','engineer_contact':'기술 이름','engineer_phone':'+82 10 1234 5678','engineer_email':'engineer@example.com'};iid,b=self.third_party(pid,**details)
  x=self.client.get('/api/data').json()['items'][0]
  for k,v in details.items():self.assertEqual(x[k],v)
  self.client.patch('/api/items/'+iid+'/lists',json={'progress_steps':[],'checklist':[],'sales_email':'discard@example.com'},headers=self.h)
  main.init_db();x=self.client.get('/api/data').json()['items'][0]
  for k,v in details.items():self.assertEqual(x[k],v)
  wb=load_workbook(io.BytesIO(self.client.get('/api/export.xlsx',params={'scope':'third_party','project_id':pid}).content));rows=list(wb.active.values);record=dict(zip(rows[0],rows[1]))
  for label,key in [('담당 영업 이름','sales_contact'),('담당 영업 연락처','sales_phone'),('담당 영업 메일','sales_email'),('담당 엔지니어 이름','engineer_contact'),('담당 엔지니어 연락처','engineer_phone'),('담당 엔지니어 메일','engineer_email')]:self.assertEqual(record[label],details[key])
  details.update(sales_phone='',engineer_email='new@example.com');batch={'project_id':pid,'items':[{'sheet':'3rd-party','row':2,'id':iid,'data':{'kind':'third_party',**details}}]};commit,_=self.import_preview(batch);self.client.post('/api/import/commit',json=commit,headers=self.h);x=self.client.get('/api/data').json()['items'][0]
  for k,v in details.items():self.assertEqual(x[k],v)

if __name__=='__main__':unittest.main()
