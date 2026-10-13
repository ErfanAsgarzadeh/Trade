"""Administrative provisioning. Passwords are entered locally, never CLI arguments."""
import argparse
import getpass
import os
from pathlib import Path
import re
import sqlite3

from cryptography.fernet import Fernet
from customer_manager import private_write
from portal_store import PortalStore,password_hash
from portal_database import configured_target,PortalDatabase
from portal_jobs import AccountQueue


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default=None,help='Local SQLite path; PostgreSQL URL preferably supplied via secret file')
    parser.add_argument('--key-file',type=Path,default=Path(os.getenv('PORTAL_KEY_FILE','issuer-keys/portal.key')))
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('init')
    sub.add_parser('queue-status')
    migration=sub.add_parser('migrate-database');migration.add_argument('--source',type=Path,required=True)
    for name in ('create-user','reset-password','disable-user','bind-runtime'):
        command=sub.add_parser(name);command.add_argument('username')
        if name=='bind-runtime':command.add_argument('runtime',type=Path)
    args=parser.parse_args()
    target=args.db or configured_target()
    store=None
    try:
        if args.action=='init':
            if args.key_file.exists():raise ValueError('Encryption key exists; never replace an existing key')
            if not str(target).startswith(('postgres://','postgresql://')) and Path(target).exists():
                raise ValueError('Database exists; do not replace its encryption key')
            if str(target).startswith(('postgres://','postgresql://')):
                probe=PortalDatabase(target)
                try:
                    with probe.db() as db:
                        if db.execute('SELECT COUNT(*) AS count FROM users').fetchone()['count']:
                            raise ValueError('Existing users; restore the existing encryption key')
                finally:probe.close()
            private_write(args.key_file,Fernet.generate_key()+b'\n')
            store=PortalStore(target,args.key_file.read_bytes().strip())
            print('Portal initialized. Back up the database and encryption key separately.');return
        if args.action=='migrate-database':
            from portal_migrate import migrate_sqlite
            print(migrate_sqlite(args.source,target,args.key_file.read_bytes().strip()));return
        store=PortalStore(target,args.key_file.read_bytes().strip())
        if args.action=='queue-status':print(AccountQueue(store).summary());return
        if not re.fullmatch(r'[a-z][a-z0-9-]{1,39}',args.username):raise ValueError('Invalid username')
        if args.action in ('create-user','reset-password'):
            password=getpass.getpass('Password (12..128 characters): ')
            if not 12<=len(password)<=128 or password!=getpass.getpass('Repeat password: '):
                raise ValueError('Password length or confirmation invalid')
            if args.action=='create-user':store.create_user(args.username,password)
            else:
                with store.db() as db:
                    user=db.execute('SELECT id FROM users WHERE username=?',(args.username,)).fetchone()
                    if not user:raise ValueError('Unknown user')
                    db.execute('UPDATE users SET password=? WHERE id=?',(password_hash(password),user['id']))
                    db.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
        else:
            with store.db() as db:
                user=db.execute('SELECT id FROM users WHERE username=?',(args.username,)).fetchone()
                if not user:raise ValueError('Unknown user')
                if args.action=='disable-user':
                    db.execute('UPDATE users SET disabled=1 WHERE id=?',(user['id'],))
                    db.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
            if args.action=='bind-runtime':store.bind_runtime(user['id'],args.runtime)
        print('Completed.')
    except (ValueError,OSError,sqlite3.Error) as exc:parser.exit(2,str(exc)+'\n')
    except Exception:parser.exit(2,'Database operation failed; check configuration without exposing credentials.\n')
    finally:
        if store:store.close()


if __name__=='__main__':main()
