"""Administrative authorization and bounded, secret-free audit metadata."""
import json
import time
import uuid


def require_admin(db,actor):
    row=db.execute('SELECT role,disabled FROM users WHERE id=?',(actor,)).fetchone()
    if not row or row['role']!='admin' or row['disabled']:raise PermissionError('Administrator required')


def record(db,actor,action,target,details=None):
    db.execute('INSERT INTO admin_events(id,actor_id,action,target,details,at) VALUES(?,?,?,?,?,?)',
               (str(uuid.uuid4()),actor,action,target,json.dumps(details or {},ensure_ascii=False,allow_nan=False),time.time()))
