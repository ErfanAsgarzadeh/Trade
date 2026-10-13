"""Central account portal pilot, separate from the single-customer bot dashboard."""
from contextlib import asynccontextmanager
import os
import ipaddress
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.middleware.trustedhost import TrustedHostMiddleware

from portal_store import PortalStore
from portal_database import configured_target
from portal_jobs import AccountQueue,MissingConnection,RefreshLimited,QueueFull
from portal_runtime import robots
from portal_exchanges import catalog,validate_connection,UnsupportedAccount

COOKIE='trade_session'


def trusted_proxies(value):
    if not value.strip():return ''
    hosts=[v.strip() for v in value.split(',')]
    if len(hosts)>16 or any(v=='*' or not v for v in hosts):
        raise ValueError('Specify explicit proxy IP addresses or CIDRs; wildcard trust is forbidden')
    return ','.join(str(ipaddress.ip_network(v,strict=False)) for v in hosts)


class Login(BaseModel):
    model_config=ConfigDict(extra='forbid')
    username:str=Field(min_length=2,max_length=40,pattern=r'^[a-z][a-z0-9-]+$')
    password:SecretStr=Field(min_length=12,max_length=128)


class Connection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    market:str=Field(pattern=r'^(spot|futures)$')
    api_key:SecretStr=Field(min_length=8,max_length=512)
    secret:SecretStr=Field(min_length=8,max_length=8192)
    exchange_id:str=Field(default='lbank',min_length=2,max_length=40,pattern=r'^[a-z0-9]+$')
    passphrase:SecretStr|None=Field(default=None,max_length=512)
    uid:SecretStr|None=Field(default=None,max_length=128)


def create_app(store=None,reader=None,origin=None,secure=None):
    origin=origin or os.getenv('PORTAL_ORIGIN','http://127.0.0.1:8080')
    origin=origin.rstrip('/')
    parsed=urlsplit(origin)
    secure=(os.getenv('PORTAL_ALLOW_LOCAL_HTTP','0')!='1') if secure is None else secure
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('PORTAL_ORIGIN must be an absolute origin without a path')
    if parsed.scheme!='https' and (secure or parsed.hostname not in ('127.0.0.1','localhost','::1')):
        raise ValueError('HTTPS required except explicit loopback development mode')
    if parsed.scheme=='https' and not secure:
        raise ValueError('HTTPS deployments require secure session cookies')
    supplied_store=store
    if reader is not None:
        raise ValueError('Exchange readers run in portal_worker, never in the web process')

    @asynccontextmanager
    async def lifespan(app):
        if supplied_store is None:
            key=Path(os.environ['PORTAL_KEY_FILE']).read_bytes().strip()
            app.state.store=PortalStore(configured_target(),key)
        else:app.state.store=supplied_store
        try:yield
        finally:
            if supplied_store is None:app.state.store.close()

    app=FastAPI(title='Trade customer portal',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=[parsed.hostname])

    def repository(request:Request):return request.app.state.store

    def identity(request:Request):
        user=repository(request).session(request.cookies.get(COOKIE,''))
        if not user:raise HTTPException(401,'Login required')
        return user

    def same_origin(request):
        if request.headers.get('X-Portal-Request')!='1' or request.headers.get('Origin',origin)!=origin:
            raise HTTPException(403,'Invalid request origin')

    def mutation(request:Request,user=Depends(identity)):
        same_origin(request)
        if not secrets.compare_digest(request.headers.get('X-CSRF-Token',''),user['csrf']):
            raise HTTPException(403,'Invalid request token')
        return user

    @app.middleware('http')
    async def headers(request,call_next):
        # Protect key/password uploads before JSON validation. Reject ambiguous streaming bodies.
        if request.method in ('POST','PUT','PATCH'):
            try:length=int(request.headers.get('Content-Length','0'))
            except ValueError:return JSONResponse({'detail':'Invalid request'},status_code=400)
            if request.headers.get('Transfer-Encoding') or not 0<=length<=16384:
                return JSONResponse({'detail':'Request too large'},status_code=413)
            body=await request.body()
            if len(body)>16384:return JSONResponse({'detail':'Request too large'},status_code=413)
        response=await call_next(request)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
                                 'X-Frame-Options':'DENY','Referrer-Policy':'no-referrer',
                                 'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        if secure:response.headers['Strict-Transport-Security']='max-age=31536000'
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request,error):
        # FastAPI's default validation includes submitted inputs, including API secrets.
        return JSONResponse({'detail':'Invalid fields; check input length and required fields'},status_code=422)

    try:
        from psycopg_pool import PoolTimeout,TooManyRequests
    except ImportError:pass
    else:
        async def database_busy(request,error):
            return JSONResponse({'detail':'Database busy; retry later'},status_code=503)
        app.add_exception_handler(PoolTimeout,database_busy)
        app.add_exception_handler(TooManyRequests,database_busy)

    @app.get('/',response_class=HTMLResponse)
    def home():return Path(__file__).with_name('portal.html').read_text(encoding='utf-8')

    @app.get('/portal.js')
    def script():return Response(Path(__file__).with_name('portal.js').read_text(),media_type='application/javascript')

    @app.get('/portal.css')
    def css():return Response(Path(__file__).with_name('portal.css').read_text(),media_type='text/css')

    @app.get('/healthz')
    def health(request:Request):
        try:
            with repository(request).db() as db:db.execute('SELECT 1')
        except Exception:raise HTTPException(503,'Database unavailable')
        return {'status':'ok'}

    @app.post('/api/login')
    def login(payload:Login,request:Request,response:Response):
        same_origin(request)
        store=repository(request)
        client=request.client.host if request.client else 'unknown'
        if not store.attempt(client):raise HTTPException(429,'Too many login attempts; retry in one minute')
        session=store.login(payload.username,payload.password.get_secret_value())
        if not session:raise HTTPException(401,'Invalid credentials')
        # Rotation invalidates an already logged-in session for this browser.
        store.logout(request.cookies.get(COOKIE,''))
        token,csrf=session
        response.set_cookie(COOKIE,token,httponly=True,secure=secure,samesite='strict',max_age=43200,path='/')
        return {'csrf':csrf}

    @app.post('/api/logout')
    def logout(request:Request,response:Response,user=Depends(mutation)):
        repository(request).logout(request.cookies.get(COOKIE,''))
        response.delete_cookie(COOKIE,path='/',secure=secure,httponly=True,samesite='strict')
        return {'status':'logged_out'}

    @app.get('/api/me')
    def me(user=Depends(identity)):
        return dict(username=user['username'],csrf=user['csrf'],live_execution_supported=False)

    @app.get('/api/exchanges',dependencies=[Depends(identity)])
    def exchanges():return {'exchanges':catalog(),'live_execution_supported':False}

    @app.get('/api/me/connection')
    def connection(request:Request,user=Depends(identity)):
        return {**repository(request).public_connection(user['id']),'live_execution_supported':False}

    @app.put('/api/me/connection')
    def save(payload:Connection,request:Request,user=Depends(mutation)):
        phrase=payload.passphrase.get_secret_value() if payload.passphrase else ''
        uid=payload.uid.get_secret_value() if payload.uid else ''
        try:validate_connection(payload.exchange_id,payload.market,payload.api_key.get_secret_value(),payload.secret.get_secret_value(),phrase,uid)
        except UnsupportedAccount:raise HTTPException(422,'Exchange, market or required credentials are not supported')
        repository(request).save_connection(user['id'],payload.market,
                                            payload.api_key.get_secret_value(),payload.secret.get_secret_value(),payload.exchange_id,phrase,uid)
        return {'status':'saved_unverified','exchange_id':payload.exchange_id,'market':payload.market}

    @app.delete('/api/me/connection')
    def disconnect(request:Request,user=Depends(mutation)):
        repository(request).disconnect(user['id'])
        return {'status':'disconnected'}

    @app.post('/api/me/connection/refresh',status_code=202)
    def refresh(request:Request,user=Depends(mutation)):
        try:
            return AccountQueue(repository(request)).enqueue(user['id'])
        except MissingConnection:raise HTTPException(409,'Connect your account first')
        except RefreshLimited:raise HTTPException(429,'Account refresh limited to once per 30 seconds')
        except QueueFull:raise HTTPException(503,'Account queue is full; retry later')

    @app.get('/api/me/robots')
    def robot_status(user=Depends(identity)):
        return {'robots':robots(user['runtime'],user['username']),'live_execution_supported':False}

    return app


def main():
    import uvicorn
    proxies=trusted_proxies(os.getenv('PORTAL_TRUSTED_PROXY_IPS',''))
    uvicorn.run(create_app(),host=os.getenv('PORTAL_HOST','127.0.0.1'),port=int(os.getenv('PORTAL_PORT','8080')),
                proxy_headers=bool(proxies),forwarded_allow_ips=proxies,access_log=False)


if __name__=='__main__':main()
