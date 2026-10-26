"""Durable read-only account queue. Lease tokens fence expired and replaced workers."""
import json
import uuid


class RefreshLimited(Exception):pass
class QueueFull(Exception):pass
class MissingConnection(Exception):pass


class AccountQueue:
    def __init__(self,store,max_pending=20000,max_attempts=3):
        self.store=store;self.max_pending=max_pending;self.max_attempts=max_attempts

    def enqueue(self,owner):
        with self.store.db() as db:
            self.store.database.begin_write(db,'account-queue-capacity')
            if self.store.database.postgres:self.store.database.begin_write(db,'account:'+owner)
            now=self.store.database.clock(db)
            connection=db.execute('SELECT connections.revision FROM connections JOIN users ON users.id=connections.user_id '
                                  'WHERE user_id=? AND disabled=0',(owner,)).fetchone()
            if not connection:raise MissingConnection()
            revision=connection['revision']
            job=db.execute('SELECT state,revision FROM account_jobs WHERE user_id=?',(owner,)).fetchone()
            if job and job['revision']==revision and job['state'] in ('queued','running'):
                return {'status':'queued','already_pending':True}
            cached=db.execute('SELECT checked FROM account_cache WHERE user_id=?',(owner,)).fetchone()
            if cached and cached['checked'] and cached['checked']>now-30:raise RefreshLimited()
            count=db.execute("SELECT COUNT(*) AS count FROM account_jobs WHERE state IN ('queued','running')").fetchone()['count']
            if count>=self.max_pending:raise QueueFull()
            db.execute("INSERT INTO account_jobs VALUES(?,?,'queued',NULL,0,?,0,?) ON CONFLICT(user_id) DO UPDATE SET "
                       "revision=excluded.revision,state='queued',lease_token=NULL,lease_until=0,not_before=excluded.not_before,attempts=0,updated=excluded.updated",
                       (owner,revision,now,now))
            db.execute("INSERT INTO account_cache VALUES(?,?,NULL,0,'queued') ON CONFLICT(user_id) DO UPDATE SET status='queued'",
                       (owner,revision))
            return {'status':'queued','already_pending':False}

    def claim(self,lease_seconds=60,interval=.25,intervals=None):
        if lease_seconds<=0 or interval<0:raise ValueError('Invalid worker lease/rate')
        with self.store.db() as db:
            self.store.database.begin_write(db,'account-read-gate')
            now=self.store.database.clock(db)
            # A crashed worker after its final attempt must not leave a permanent pending job.
            exhausted=db.execute("SELECT user_id,revision FROM account_jobs WHERE state='running' AND lease_until<=? AND attempts>=?",
                                 (now,self.max_attempts)).fetchall()
            for job in exhausted:
                if self.store.database.postgres:self.store.database.begin_write(db,'account:'+job['user_id'])
                changed=db.execute("UPDATE account_jobs SET state='failed',lease_token=NULL,updated=? WHERE user_id=? AND revision=? AND state='running' AND lease_until<=?",
                           (now,job['user_id'],job['revision'],now))
                if changed.rowcount:
                    db.execute("UPDATE account_cache SET status='verification_failed',checked=? WHERE user_id=? AND revision=?",
                               (now,job['user_id'],job['revision']))
            query="SELECT j.*,c.exchange_id FROM account_jobs j JOIN connections c ON c.user_id=j.user_id AND c.revision=j.revision JOIN users u ON u.id=j.user_id LEFT JOIN service_gate g ON g.name=('account-read:' || c.exchange_id) WHERE u.disabled=0 AND j.attempts<? AND ((j.state='queued' AND j.not_before<=?) OR (j.state='running' AND j.lease_until<=?)) AND (g.next_at IS NULL OR g.next_at<=?)"
            row=db.execute(query+' ORDER BY j.not_before,j.user_id LIMIT 1',(self.max_attempts,now,now,now)).fetchone()
            if not row:return None
            if self.store.database.postgres:
                # Same owner-first lock order as rotation and completion: no job/cache deadlock.
                self.store.database.begin_write(db,'account:'+row['user_id'])
                now=self.store.database.clock(db)
                row=db.execute(query+' AND j.user_id=?',(self.max_attempts,now,now,now,row['user_id'])).fetchone()
                if not row:return None
            token=str(uuid.uuid4());until=now+lease_seconds
            db.execute("UPDATE account_jobs SET state='running',lease_token=?,lease_until=?,attempts=attempts+1,updated=? WHERE user_id=?",
                       (token,until,now,row['user_id']))
            delay=(intervals or {}).get(row['exchange_id'],interval)
            db.execute('INSERT INTO service_gate VALUES(?,?) ON CONFLICT(name) DO UPDATE SET next_at=excluded.next_at',('account-read:'+row['exchange_id'],now+delay))
            db.execute("UPDATE account_cache SET status='refreshing' WHERE user_id=? AND revision=?",(row['user_id'],row['revision']))
            return dict(row,lease_token=token,lease_until=until,attempts=row['attempts']+1,state='running')

    def finish(self,job,snapshot,status,retry=False):
        owner=job['user_id']
        with self.store.db() as db:
            self.store.database.begin_write(db,'account:'+owner)
            now=self.store.database.clock(db)
            row=db.execute('SELECT j.*,u.disabled,c.revision AS current_revision FROM account_jobs j '
                           'JOIN users u ON u.id=j.user_id JOIN connections c ON c.user_id=j.user_id WHERE j.user_id=?',
                           (owner,)).fetchone()
            if (not row or row['disabled'] or row['state']!='running' or row['lease_token']!=job['lease_token']
                or row['revision']!=job['revision'] or row['current_revision']!=job['revision'] or row['lease_until']<=now):
                return False
            retry=retry and row['attempts']<self.max_attempts
            next_run=now+min(300,30*2**(row['attempts']-1)) if retry else now
            state='queued' if retry else 'done' if status=='verified_read_only' else 'failed'
            cache_status='retrying' if retry else status
            db.execute('UPDATE account_jobs SET state=?,lease_token=NULL,lease_until=0,not_before=?,updated=? WHERE user_id=?',
                       (state,next_run,now,owner))
            db.execute('UPDATE account_cache SET snapshot=?,checked=?,status=? WHERE user_id=? AND revision=?',
                       (json.dumps(snapshot) if snapshot is not None else None,now,cache_status,owner,job['revision']))
            db.execute('INSERT INTO audit(user_id,event,at) VALUES(?,?,?)',(owner,'account_'+cache_status,now))
            return True

    def summary(self):
        with self.store.db() as db:
            rows=db.execute('SELECT state,COUNT(*) AS count FROM account_jobs GROUP BY state').fetchall()
            oldest=db.execute("SELECT MIN(not_before) AS oldest FROM account_jobs WHERE state='queued'").fetchone()['oldest']
            now=self.store.database.clock(db)
        return dict(states={r['state']:r['count'] for r in rows},oldest_due_age_seconds=max(0,now-oldest) if oldest else 0)
