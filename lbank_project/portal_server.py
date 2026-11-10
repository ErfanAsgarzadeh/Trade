"""Central account portal pilot, separate from the single-customer bot dashboard."""
from contextlib import asynccontextmanager
import os
import ipaddress
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from portal_store import PortalStore
from portal_database import configured_target
from portal_jobs import AccountQueue,MissingConnection,RefreshLimited,QueueFull
from portal_runtime import robots
from portal_exchanges import catalog,validate_connection,UnsupportedAccount
from portal_billing import Billing, BillingConflict
import product_pricing
from signal_feed import read_feed
from portal_frontend import frontend_index
from portal_admin_store import AdminStore

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


class Registration(Login):
    password_confirmation:SecretStr=Field(min_length=12,max_length=128)


class Connection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    market:str=Field(pattern=r'^(spot|futures)$')
    api_key:SecretStr=Field(min_length=8,max_length=512)
    secret:SecretStr=Field(min_length=8,max_length=8192)
    exchange_id:str=Field(default='lbank',min_length=2,max_length=40,pattern=r'^[a-z0-9]+$')
    passphrase:SecretStr|None=Field(default=None,max_length=512)
    uid:SecretStr|None=Field(default=None,max_length=128)


class LicenseQuote(BaseModel):
    model_config=ConfigDict(extra='forbid', strict=True)
    cap_usd:int=Field(ge=1000,le=100000)
    months:int=Field(ge=1,le=6)
    kind:str=Field(default='subscription',pattern=r'^(subscription|upgrade)$')
    product:str=Field(default='autotrade',pattern=r'^(signals|autotrade)$')


class LicenseOrder(LicenseQuote):
    request_key:str=Field(min_length=16,max_length=80,pattern=r'^[a-zA-Z0-9-]+$')
    expected_price_cents:int=Field(ge=1,le=20000000)


class AdminUserState(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    disabled:bool


class AdminPricing(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_version:str=Field(min_length=1,max_length=80)
    prices:dict[str,dict[str,str]]=Field(min_length=7,max_length=7)


class AdminVersion(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_version:str=Field(min_length=1,max_length=80)


class AdminOpenSales(AdminVersion):
    confirmation:str=Field(pattern=r'^FINAL_PRICES_CONFIRMED$')


class AdminRejection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    reason:str=Field(min_length=3,max_length=500)


class AdminApproval(BaseModel):
    model_config=ConfigDict(extra='forbid')
    payment_ref:str=Field(pattern=r'^[A-Za-z0-9:._-]{4,120}$')
    account_id:str|None=Field(default=None,max_length=120)
    equity_usd:str|None=Field(default=None,max_length=30)
    confirmation:str=Field(pattern=r'^PAYMENT_AND_ACCOUNT_VERIFIED$')


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
    frontend=Path(os.getenv('PORTAL_FRONTEND_DIR',str(Path(__file__).with_name('frontend')/'out')))
    public=Path(__file__).with_name('frontend')/'public'
    page_files={'/':'index.html','/register':'register.html','/register/':'register.html','/admin':'admin.html','/admin/':'admin.html','/dashboard':'dashboard.html','/dashboard/':'dashboard.html'}
    app.mount('/backtest',StaticFiles(directory=public/'backtest'),name='backtest-evidence')
    app.mount('/portal-assets',StaticFiles(directory=public/'portal-assets'),name='portal-assets')
    app.mount('/_next',StaticFiles(directory=frontend/'_next',check_dir=False),name='next-assets')

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

    def administrator(user=Depends(identity)):
        if user['role']!='admin':raise HTTPException(403,'Administrator required')
        return user

    def admin_mutation(user=Depends(mutation)):
        if user['role']!='admin':raise HTTPException(403,'Administrator required')
        return user

    def admin_call(function):
        try:return function()
        except PermissionError:raise HTTPException(403,'Administrator required')
        except LookupError:raise HTTPException(404,'Record not found')
        except BillingConflict as exc:raise HTTPException(409,str(exc))
        except ValueError as exc:
            raise HTTPException(409 if 'version changed' in str(exc).lower() else 422,'Check fields and latest version')

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
        script_hashes=''
        if request.url.path in page_files:
            try:script_hashes=frontend_index(frontend,page_files[request.url.path])[1]
            except OSError:pass
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
                                 'X-Frame-Options':'DENY','Referrer-Policy':'no-referrer',
                                 'Content-Security-Policy':f"default-src 'self'; script-src 'self' {script_hashes}; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
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
    def home():
        try:return HTMLResponse(frontend_index(frontend)[0])
        except OSError:
            return HTMLResponse('Next.js frontend is not built. Run npm ci and npm run build in lbank_project/frontend.',status_code=503)

    @app.get('/dashboard',response_class=HTMLResponse)
    @app.get('/dashboard/',response_class=HTMLResponse)
    def dashboard_page():
        try:return HTMLResponse(frontend_index(frontend,'dashboard.html')[0])
        except OSError:return HTMLResponse('Build the Next.js frontend first.',status_code=503)

    @app.get('/register',response_class=HTMLResponse)
    @app.get('/register/',response_class=HTMLResponse)
    def registration_page():
        try:return HTMLResponse(frontend_index(frontend,'register.html')[0])
        except OSError:return HTMLResponse('Build the Next.js frontend first.',status_code=503)

    @app.get('/admin',response_class=HTMLResponse)
    @app.get('/admin/',response_class=HTMLResponse)
    def admin_page():
        try:return HTMLResponse(frontend_index(frontend,'admin.html')[0])
        except OSError:return HTMLResponse('Build the Next.js frontend first.',status_code=503)

    @app.get('/api/admin/overview')
    def admin_overview(request:Request,user=Depends(administrator)):
        return AdminStore(repository(request)).overview()

    @app.get('/api/admin/users')
    def admin_users(request:Request,user=Depends(administrator),search:str=Query(default='',max_length=40),offset:int=Query(default=0,ge=0),limit:int=Query(default=30,ge=1,le=100)):
        return AdminStore(repository(request)).users(search,offset,limit)

    @app.patch('/api/admin/users/{user_id}')
    def admin_user_state(user_id:str,payload:AdminUserState,request:Request,user=Depends(admin_mutation)):
        return admin_call(lambda:AdminStore(repository(request)).set_disabled(user['id'],user_id,payload.disabled))

    @app.get('/api/admin/orders')
    def admin_orders(request:Request,user=Depends(administrator),status:str=Query(default='pending',pattern=r'^(pending|approved|cancelled|rejected|all)$'),offset:int=Query(default=0,ge=0),limit:int=Query(default=30,ge=1,le=100)):
        return AdminStore(repository(request)).orders(status,offset,limit)

    @app.post('/api/admin/orders/{order_id}/reject')
    def admin_reject(order_id:str,payload:AdminRejection,request:Request,user=Depends(admin_mutation)):
        if not payload.reason.strip():raise HTTPException(422,'Reason required')
        return admin_call(lambda:AdminStore(repository(request)).reject(user['id'],order_id,payload.reason.strip()))

    @app.post('/api/admin/orders/{order_id}/approve',status_code=202)
    def admin_approve(order_id:str,payload:AdminApproval,request:Request,user=Depends(admin_mutation)):
        return admin_call(lambda:AdminStore(repository(request)).request_approval(user['id'],order_id,payload.payment_ref,payload.account_id,payload.equity_usd))

    @app.get('/api/admin/pricing')
    def admin_pricing(request:Request,user=Depends(administrator)):
        return product_pricing.catalog(repository(request))

    @app.put('/api/admin/pricing/{product}')
    def admin_save_pricing(product:str,payload:AdminPricing,request:Request,user=Depends(admin_mutation)):
        return admin_call(lambda:product_pricing.configure(repository(request),product,payload.prices,False,payload.expected_version,user['id']))

    @app.post('/api/admin/pricing/{product}/open')
    def admin_open_sales(product:str,payload:AdminOpenSales,request:Request,user=Depends(admin_mutation)):
        return admin_call(lambda:product_pricing.open_sales(repository(request),product,payload.expected_version,user['id']))

    @app.post('/api/admin/pricing/{product}/close')
    def admin_close_sales(product:str,payload:AdminVersion,request:Request,user=Depends(admin_mutation)):
        admin_call(lambda:product_pricing.close_sales(repository(request),product,payload.expected_version,user['id']))
        return {'status':'closed'}

    @app.get('/api/admin/audit')
    def admin_events(request:Request,user=Depends(administrator),offset:int=Query(default=0,ge=0),limit:int=Query(default=30,ge=1,le=100)):
        return AdminStore(repository(request)).events(offset,limit)

    @app.get('/manifest.webmanifest')
    def manifest():
        return Response((public/'manifest.webmanifest').read_text(),media_type='application/manifest+json')

    @app.get('/portal-sw.js')
    def service_worker():
        return Response((public/'portal-sw.js').read_text(),media_type='application/javascript',
                        headers={'Service-Worker-Allowed':'/'})

    @app.get('/api/plans')
    def plans(request:Request):return product_pricing.catalog(repository(request))

    @app.get('/api/me/license')
    def subscription(request:Request,user=Depends(identity)):
        return Billing(repository(request)).snapshot(user['id'])

    @app.post('/api/me/license/quote')
    def quote_license(payload:LicenseQuote,request:Request,user=Depends(mutation)):
        try:return Billing(repository(request)).quote(user['id'],payload.cap_usd,payload.months,payload.kind,product=payload.product)
        except BillingConflict as exc:raise HTTPException(409,str(exc))
        except ValueError:raise HTTPException(422,'Unknown tier or term')

    @app.post('/api/me/license/orders',status_code=201)
    def request_license(payload:LicenseOrder,request:Request,user=Depends(mutation)):
        try:return Billing(repository(request)).order(user['id'],payload.cap_usd,payload.months,payload.kind,
                    payload.request_key,payload.expected_price_cents,product=payload.product)
        except BillingConflict as exc:raise HTTPException(409,str(exc))
        except ValueError:raise HTTPException(422,'Unknown tier or term')

    @app.post('/api/me/license/orders/{order_id}/cancel')
    def cancel_license(order_id:str,request:Request,user=Depends(mutation)):
        try:Billing(repository(request)).cancel(user['id'],order_id)
        except BillingConflict:raise HTTPException(404,'Pending order not found')
        return {'status':'cancelled'}

    @app.get('/api/me/license/download')
    def download_license(request:Request,user=Depends(identity)):
        try:document=Billing(repository(request)).document(user['id'])
        except BillingConflict:raise HTTPException(404,'No issued license')
        return Response(document,media_type='application/json',
                        headers={'Content-Disposition':'attachment; filename="trade-license.json"'})

    @app.get('/healthz')
    def health(request:Request):
        try:
            with repository(request).db() as db:db.execute('SELECT 1')
        except Exception:raise HTTPException(503,'Database unavailable')
        return {'status':'ok'}

    @app.post('/api/register',status_code=201)
    def register(payload:Registration,request:Request,response:Response):
        same_origin(request)
        store=repository(request)
        client=request.client.host if request.client else 'unknown'
        if not store.attempt('signup:'+client):raise HTTPException(429,'Too many signup attempts')
        password=payload.password.get_secret_value()
        if not secrets.compare_digest(password.encode(),payload.password_confirmation.get_secret_value().encode()):
            raise HTTPException(422,'Password confirmation does not match')
        try:token,csrf=store.register(payload.username,password)
        except ValueError:raise HTTPException(409,'Username unavailable')
        store.logout(request.cookies.get(COOKIE,''))
        response.set_cookie(COOKIE,token,httponly=True,secure=secure,samesite='strict',max_age=43200,path='/')
        return {'username':payload.username,'csrf':csrf}

    @app.get('/api/me/signals')
    def signals(request:Request,user=Depends(identity)):
        entitlement=Billing(repository(request)).snapshot(user['id'])['license']
        if not entitlement.get('signals_allowed',False):raise HTTPException(403,'An active subscription is required')
        return read_feed(os.getenv('PORTAL_SIGNAL_FEED_DB',''))

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
        return dict(username=user['username'],csrf=user['csrf'],role=user['role'],live_execution_supported=False)

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
