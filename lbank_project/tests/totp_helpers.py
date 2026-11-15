"""Authenticator stand-in for tests: administrators need two-step login before they can change anything."""
import portal_security
import portal_totp

AUTH = {}   # username -> Authenticator, for users whose test login needs a code (cleared for every test)
SKEW = {'seconds': 0}   # Seconds the server-side TOTP clock is ahead; every code() moves it one step so no step is reused.


class Authenticator:
    def __init__(self, secret, recovery=()):
        self.secret, self.recovery = secret, list(recovery)

    def code(self):
        SKEW['seconds'] += portal_totp.PERIOD
        return portal_totp.code_at(self.secret, int(portal_totp.now() // portal_totp.PERIOD))


def enable_totp(store, username):
    """Turn two-step login on for a user the way the API does and return the authenticator."""
    with store.db() as db:user = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()['id']
    secret = portal_security.setup(store, user)['secret']
    SKEW['seconds'] += portal_totp.PERIOD
    codes = portal_security.enable(store, user, portal_totp.code_at(secret, int(portal_totp.now() // portal_totp.PERIOD)))
    assert codes and len(codes) == 10
    AUTH[username] = Authenticator(secret, codes)
    return AUTH[username]


def extra(username):
    """Login fields that carry a fresh code for a user with two-step login."""
    return {'totp': AUTH[username].code()} if username in AUTH else {}


def signup_token(store):
    """A sign-up form token that is already old enough (the server wants the form open for at least 3 seconds)."""
    import time
    return store.form_token(now=time.time() - 10)


def login_headers(client, username, password, origin, authenticator=None):
    """Sign in (with a two-step code when given) and return the headers every mutation needs."""
    body = dict(username=username, password=password)
    if authenticator:body['totp'] = authenticator.code()
    r = client.post('/api/login', headers={'X-Portal-Request': '1', 'Origin': origin}, json=body)
    assert r.status_code == 200, r.text
    return {'X-Portal-Request': '1', 'Origin': origin, 'X-CSRF-Token': r.json()['csrf']}
