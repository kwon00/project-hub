"""Manage local accounts from the application container; passwords are prompted."""
import argparse
import getpass
import re
import secrets
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import db, init_db, hash_password
p = argparse.ArgumentParser(description='Project Hub account management')
sub = p.add_subparsers(dest='command', required=True)
sub.add_parser('list')
for command in ['add', 'rename', 'disable', 'enable', 'password']:
    action = sub.add_parser(command)
    action.add_argument('username')
    if command in ['add', 'rename']:
        action.add_argument('--name', required=True)
a = p.parse_args()
if a.command != 'list' and not re.fullmatch(r'[a-zA-Z0-9_.@-]{1,100}', a.username):
    p.error('계정 ID는 영문, 숫자, _, ., @, -만 사용할 수 있습니다 (최대 100자).')
if a.command in ['add', 'rename'] and (not a.name.strip() or len(a.name) > 100):
    p.error('이름은 1~100자여야 합니다.')
encoded = None
if a.command in ['add', 'password']:
    pw = getpass.getpass('새 비밀번호 (12자 이상): ')
    if pw != getpass.getpass('비밀번호 확인: '):
        p.error('비밀번호가 일치하지 않습니다.')
    try: encoded = hash_password(pw)
    except ValueError as e: p.error(str(e))
init_db()
with db() as con:
    if a.command == 'list':
        for r in con.execute('SELECT username,name,active FROM users ORDER BY username'):
            print(f'{r["username"]}\t{r["name"]}\t{"활성" if r["active"] else "비활성"}')
    elif a.command == 'add':
        if con.execute('SELECT 1 FROM users WHERE username=?', (a.username,)).fetchone():
            p.error('이미 존재하는 계정입니다.')
        con.execute('INSERT INTO users(id,username,name,password_hash) VALUES(?,?,?,?)', (secrets.token_hex(12), a.username, a.name.strip(), encoded))
        print('계정을 추가했습니다.')
    else:
        if not con.execute('SELECT 1 FROM users WHERE username=?', (a.username,)).fetchone():
            p.error('계정을 찾을 수 없습니다.')
        if a.command == 'rename':
            con.execute('UPDATE users SET name=? WHERE username=?', (a.name.strip(), a.username))
        elif a.command == 'password':
            con.execute('UPDATE users SET password_hash=?,session_version=session_version+1 WHERE username=?', (encoded, a.username))
        else:
            con.execute('UPDATE users SET active=?,session_version=session_version+1 WHERE username=?', (int(a.command == 'enable'), a.username))
        print('계정을 변경했습니다.')
