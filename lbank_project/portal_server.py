"""Central account portal pilot, separate from the single-customer bot dashboard."""
from contextlib import asynccontextmanager
import os
import ipaddress
import json
import logging
from pathlib import Path
import hashlib
import re
import secrets
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.routing import Match
from fastapi.staticfiles import StaticFiles

from portal_store import normal_email as portal_store_email, EmailTaken, LoginLocked, PortalStore, SESSION_SECONDS, TwoFactorRequired
import portal_security
from portal_database import configured_target
from portal_jobs import AccountQueue,MissingConnection,RefreshLimited,QueueFull
from portal_runtime import robots
from portal_exchanges import catalog,validate_connection,PERMISSION_CHECKS,UnsupportedAccount
from portal_billing import Billing, BillingConflict, PaidOrderConflict
import product_pricing
from signal_feed import read_feed
from portal_frontend import PUBLIC_PAGES, PRIVATE_PAGES, SERVER_PAGES, frontend_index, localize, page_lang, private_page, public_file, public_page, robots_txt, sitemap_xml
import portal_blog
import portal_forward
import portal_pages
import portal_site
import portal_mail
import portal_watchdog
from portal_edge import TTLCache, TokenBuckets
from portal_payments import PaymentConflict, Payments
from portal_telegram import Telegram, TelegramError
from portal_referrals import ReferralConflict, Referrals
from portal_blog import BlogConflict, BlogStore
from portal_admin_store import AdminStore
from portal_request_models import (
    Credentials,
    Login,
    Registration,
    EmailChange,
    VerifyResend,
    PasswordChange,
    ResetRequest,
    ResetConfirm,
    TotpSetup,
    TotpEnable,
    TotpDisable,
    Connection,
    LicenseQuote,
    LicenseOrder,
    AdminUserState,
    AdminPricing,
    AdminVersion,
    AdminOpenSales,
    AdminRejection,
    AdminRefund,
    TransferAttach,
    BlogArticle,
    InvoiceRequest,
    PaymentSettings,
    TelegramPreferences,
    TelegramLink,
    SiteInfo,
    ForwardSwitch,
    TelegramSettings,
    TelegramBroadcast,
    ReferralCode,
    ReferralSettings,
    ReferralProgram,
    AdminReferralCode,
    ReferralGrant,
    AdminApproval,
)

COOKIE='trade_session'
LOG=logging.getLogger('portal.errors')
RATE_EXEMPT=('/_next/','/portal-assets/','/blog-media/','/backtest/')   # Static files; /healthz is exempt too.
RATE_LIMITED_API={'/api/plans','/api/blog/latest','/api/register/token','/api/forward-test'}   # Public API routes; signed-in polling is not counted.
NOT_PAGES=('/api/','/_next/','/portal-assets/','/backtest/','/blog-media/')


def error_location(error):
    """'file.py:line in function' of the innermost frame: where it failed, never what the message said."""
    trace=error.__traceback__
    while trace and trace.tb_next:trace=trace.tb_next
    return f'{Path(trace.tb_frame.f_code.co_filename).name}:{trace.tb_lineno} in {trace.tb_frame.f_code.co_name}' if trace else 'unknown'


def trusted_proxies(value):
    if not value.strip():return ''
    hosts=[v.strip() for v in value.split(',')]
    if len(hosts)>16 or any(v=='*' or not v for v in hosts):
        raise ValueError('Specify explicit proxy IP addresses or CIDRs; wildcard trust is forbidden')
    return ','.join(str(ipaddress.ip_network(v,strict=False)) for v in hosts)


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
            from portal_store import keys_from_env
            key,settings_key=keys_from_env()
            app.state.store=PortalStore(configured_target(),key,settings_key)
        else:app.state.store=supplied_store
        if hasattr(app.state.store,'database'):
            app.state.store.rekey_settings()  # Site secrets move from the portal key to the settings key once both are present.
            BlogStore(app.state.store).seed()
        app.state.forward=portal_forward.ForwardTest(app.state.store) if hasattr(app.state.store,'database') else None
        try:yield
        finally:
            if supplied_store is None:app.state.store.close()

    app=FastAPI(title='Trade customer portal',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=[parsed.hostname])
    frontend=Path(os.getenv('PORTAL_FRONTEND_DIR',str(Path(__file__).with_name('frontend')/'out')))
    public=Path(__file__).with_name('frontend')/'public'
    page_files={**PUBLIC_PAGES,**PRIVATE_PAGES,**{p.rstrip('/'):f for p,f in {**PUBLIC_PAGES,**PRIVATE_PAGES}.items() if p!='/'}}
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
        # Reading stays possible so an administrator can sign in and set up two-step login; changing anything needs it.
        if not user['totp_enabled']:raise HTTPException(403,'Two-factor setup required')
        return user

    def queue_verification(store,user,email,lang,by_username=True):
        """Queue the verification link (a database row; the worker sends it). Never allowed to break the request."""
        try:
            with store.db() as db:
                if by_username:
                    row=db.execute('SELECT id FROM users WHERE username=?',(user,)).fetchone()
                    user=row['id'] if row else None
                if user:portal_mail.request_verification(db,user,portal_store_email(email),origin,lang)
        except Exception:pass

    def throttled(request,user):
        """Codes and passwords are only checked at a bounded rate per account."""
        if not repository(request).attempt('reauth:'+user['id']):raise HTTPException(429,'Too many attempts; retry in one minute')

    def reauthenticate(request,user,password):
        throttled(request,user)
        if not repository(request).password_matches(user['id'],password.get_secret_value()):raise HTTPException(403,'Current password is incorrect')

    def step_up(request,user,code):
        throttled(request,user)
        if not portal_security.step_up(repository(request),user['id'],code):raise HTTPException(403,'Invalid two-factor code')

    def set_session_cookie(response,token,role):
        response.set_cookie(COOKIE,token,httponly=True,secure=secure,samesite='strict',max_age=SESSION_SECONDS.get(role,SESSION_SECONDS['customer']),path='/')

    def admin_call(function):
        try:return function()
        except PermissionError:raise HTTPException(403,'Administrator required')
        except LookupError:raise HTTPException(404,'Record not found')
        except BillingConflict as exc:raise HTTPException(409,str(exc))
        except ValueError as exc:
            raise HTTPException(409 if 'version changed' in str(exc).lower() else 422,'Check fields and latest version')

    def blog_posts(request,lang='fa'):
        store=repository(request)
        return BlogStore(store).published(lang) if hasattr(store,'database') else []

    def site_css():
        try:return portal_blog.stylesheets(frontend_index(frontend)[0])
        except OSError:return []

    buckets=TokenBuckets(int(os.getenv('PORTAL_RATE_LIMIT_PER_MINUTE','120')))
    pages=TTLCache(30)

    def cached_page(key,build):
        """Blog pages are rendered at most once per 30 seconds per path and language, and again right after any blog write."""
        generation=portal_blog.GENERATION[0]
        hit=pages.get(key,generation)
        return hit if hit is not None else pages.put(key,build(),generation)

    def etagged(request,body,status_code=200):
        """HTML with a strong ETag from the content hash. The body already differs per language and per page, so the tag
        does too; a matching If-None-Match gets a bodyless 304 and the middleware still adds the CSP and cache headers."""
        tag='"'+hashlib.sha256(body.encode()).hexdigest()[:32]+'"'
        offered=[v.strip() for v in request.headers.get('If-None-Match','').split(',')]
        if status_code==200 and (tag in offered or '*' in offered):return Response(status_code=304,headers={'ETag':tag})
        return HTMLResponse(body,status_code=status_code,headers={'ETag':tag})

    @app.middleware('http')
    async def rate_limit(request,call_next):
        # Page loads and public API reads only; a browser fetching its own panel data or static files is never counted.
        path=request.url.path
        if (request.method in ('GET','HEAD') and path!='/healthz' and not path.startswith(RATE_EXEMPT)
                and (not path.startswith('/api/') or path in RATE_LIMITED_API)):
            wait=buckets.take(request.client.host if request.client else 'unknown')
            if wait:return JSONResponse({'detail':'Too many requests; slow down'},status_code=429,headers={'Retry-After':str(wait)})
        return await call_next(request)

    @app.middleware('http')
    async def headers(request,call_next):
        # Protect key/password uploads before JSON validation. Reject ambiguous streaming bodies.
        if request.method in ('POST','PUT','PATCH'):
            try:length=int(request.headers.get('Content-Length','0'))
            except ValueError:return JSONResponse({'detail':'Invalid request'},status_code=400)
            # Article bodies are the one larger payload; credentials and everything else stay at 16 KiB.
            if request.url.path=='/api/admin/blog/images':limit=portal_blog.MAX_UPLOAD
            elif request.url.path.startswith('/api/admin/blog'):limit=262144
            else:limit=16384
            if request.headers.get('Transfer-Encoding') or not 0<=length<=limit:
                return JSONResponse({'detail':'Request too large'},status_code=413)
            body=await request.body()
            if len(body)>limit:return JSONResponse({'detail':'Request too large'},status_code=413)
        try:response=await call_next(request)
        except Exception as error:
            # One line: request id, method, path, exception type and where it failed. No bodies, headers or exception text.
            request_id=secrets.token_hex(4)
            LOG.error('unhandled error id=%s method=%s path=%s type=%s at=%s',request_id,request.method,
                      json.dumps(request.url.path[:200]),type(error).__name__,error_location(error))
            response=JSONResponse({'detail':'Internal error','request_id':request_id},status_code=500)
        path=request.url.path
        blog_page=path in ('/blog','/en/blog') or path.startswith(('/blog/','/en/blog/'))
        public=public_file(path) or blog_page and response.status_code==200 or path in SERVER_PAGES
        page=page_files.get(path) or (public[1] if isinstance(public,tuple) else None)
        if response.status_code==404 and (blog_page or response.headers.get('content-type','').startswith('text/html')):page='404.html'
        script_hashes=''
        if page:
            try:script_hashes=frontend_index(frontend,page)[1]
            except OSError:pass
        # Hashed build files never change; brand assets may. Public pages revalidate; everything else is private.
        if path.startswith('/_next/static/'):cache='public, max-age=31536000, immutable'
        elif path.startswith('/portal-assets/'):cache='public, max-age=86400'
        # An uploaded image never changes under its id; a new upload gets a new id.
        elif path.startswith('/blog-media/') and response.status_code==200:cache='public, max-age=31536000, immutable'
        elif path.startswith('/backtest/') or path in ('/robots.txt','/sitemap.xml','/blog/rss.xml','/en/blog/rss.xml'):cache='public, max-age=3600'
        elif path=='/api/forward-test' and response.status_code==200:cache='public, max-age=300'
        elif public:cache='no-cache'
        else:
            cache='no-store'
            response.headers['X-Robots-Tag']='noindex, nofollow'
        if response.status_code>=400:cache='no-store'
        if path.startswith('/backtest/') and path.endswith('.md'):response.headers['X-Robots-Tag']='noindex'
        response.headers.update({'Cache-Control':cache,'X-Content-Type-Options':'nosniff',
                                 'X-Frame-Options':'DENY','Referrer-Policy':'no-referrer',
                                 # Wallet payments use the injected window.ethereum provider, which none of these features touch.
                                 'Permissions-Policy':'camera=(), microphone=(), geolocation=(), payment=()',
                                 'Cross-Origin-Opener-Policy':'same-origin',
                                 'Content-Security-Policy':f"default-src 'self'; script-src 'self' {script_hashes}; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        if secure:response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
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

    def not_built():
        return HTMLResponse('Next.js frontend is not built. Run npm ci and npm run build in lbank_project/frontend.',status_code=503)

    def not_found(request=None):
        lang=page_lang(request.url.path) if request else 'fa'
        try:return HTMLResponse(localize(frontend_index(frontend,'404.html')[0],lang),status_code=404)
        except OSError:return HTMLResponse('Not found',status_code=404)

    # Public pages in both languages. Every address without its trailing slash is permanently redirected to the canonical one.
    def public_pages(request:Request):
        try:return etagged(request,public_page(frontend,request.url.path,origin))
        except OSError:return not_built()

    def canonical_redirect(request:Request):
        target=request.url.path+'/'
        if request.url.query:target+='?'+request.url.query
        return RedirectResponse(target,status_code=308)

    for address in PUBLIC_PAGES:
        app.add_api_route(address,public_pages,methods=['GET'],response_class=HTMLResponse)
    def server_page(request:Request):
        path=request.url.path;slug=portal_pages.slug_of(path);lang=page_lang(path)
        store=repository(request)
        def build():
            plans=product_pricing.catalog(store) if hasattr(store,'database') else None
            info=portal_site.read(store) if hasattr(store,'database') else {}
            return portal_pages.build(slug,lang,origin,site_css(),plans,catalog(),info)
        return etagged(request,cached_page(('page',path),build))

    for address in SERVER_PAGES:
        app.add_api_route(address,server_page,methods=['GET'],response_class=HTMLResponse)
    for address in (*PUBLIC_PAGES,*PRIVATE_PAGES,*SERVER_PAGES):
        if address!='/':app.add_api_route(address.rstrip('/'),canonical_redirect,methods=['GET'],response_class=HTMLResponse)

    # Signed-in pages: the client checks the session; the server serves the same shell to everyone.
    def private_pages(request:Request):
        try:return HTMLResponse(private_page(frontend,page_files[request.url.path]))
        except OSError:return not_built()

    for address in PRIVATE_PAGES:
        app.add_api_route(address,private_pages,methods=['GET'],response_class=HTMLResponse)

    @app.get('/blog/rss.xml')
    @app.get('/en/blog/rss.xml')
    def blog_feed(request:Request):
        lang='en' if request.url.path.startswith('/en/') else 'fa'
        body=cached_page(('rss',lang),lambda:portal_blog.rss_xml(origin,blog_posts(request,lang),lang))
        return Response(body,media_type='application/rss+xml; charset=utf-8')

    @app.get('/blog',response_class=HTMLResponse)
    @app.get('/en/blog',response_class=HTMLResponse)
    def blog_index_redirect(request:Request):return canonical_redirect(request)

    @app.get('/blog/',response_class=HTMLResponse)
    @app.get('/en/blog/',response_class=HTMLResponse)
    def blog_index(request:Request):
        lang='en' if request.url.path.startswith('/en/') else 'fa'
        return etagged(request,cached_page(('index',lang),lambda:portal_blog.index_page(origin,site_css(),blog_posts(request,lang),lang)))

    @app.get('/blog/{slug}',response_class=HTMLResponse)
    @app.get('/en/blog/{slug}',response_class=HTMLResponse)
    def blog_article_redirect(slug:str,request:Request):return canonical_redirect(request)

    @app.get('/blog/{slug}/',response_class=HTMLResponse)
    @app.get('/en/blog/{slug}/',response_class=HTMLResponse)
    def blog_article(slug:str,request:Request):
        lang='en' if request.url.path.startswith('/en/') else 'fa'
        store=repository(request)
        if not hasattr(store,'database'):return not_found(request)
        key=('article',lang,slug);generation=portal_blog.GENERATION[0]
        hit=pages.get(key,generation)
        if hit is not None:return etagged(request,hit)
        blog=BlogStore(store);post=blog.article(slug,lang)
        if not post:return not_found(request)   # Unknown addresses are never cached, so random paths cannot fill the cache.
        related=[item for item in blog_posts(request,lang) if item['slug']!=post['slug']][:3]
        sizes=blog.image_sizes(portal_blog.image_ids(post['body']))
        return etagged(request,pages.put(key,portal_blog.article_page(origin,site_css(),post,related,blog.translations(slug),lang,sizes),generation))

    @app.get('/blog-media/{name}')
    def blog_media(name:str,request:Request):
        store=repository(request)
        match=re.fullmatch(r'([a-f0-9]{16,32})\.webp',name)
        data=BlogStore(store).image(match[1]) if match and hasattr(store,'database') else None
        if data is None:return Response('Not found',status_code=404,media_type='text/plain')
        return Response(data,media_type='image/webp')

    @app.get('/api/blog/latest')
    def blog_latest(request:Request,limit:int=Query(default=3,ge=1,le=12),lang:str=Query(default='fa',pattern=r'^(fa|en)$')):
        return {'items':[dict(slug=p['slug'],title=p['title'],description=p['description'],published_on=p['published_on'],
                              date_label=portal_blog.date_label(p['published_on'],lang),minutes=p['minutes'])
                         for p in blog_posts(request,lang)[:limit]]}

    @app.get('/api/admin/overview')
    def admin_overview(request:Request,user=Depends(administrator)):
        return AdminStore(repository(request)).overview()

    @app.get('/api/admin/health')
    def admin_health(request:Request,user=Depends(administrator)):
        return [{k:v for k,v in item.items() if k!='fingerprint'} for item in portal_watchdog.health(repository(request))]

    @app.get('/api/admin/users')
    def admin_users(request:Request,user=Depends(administrator),search:str=Query(default='',max_length=80),offset:int=Query(default=0,ge=0),limit:int=Query(default=30,ge=1,le=100)):
        return AdminStore(repository(request)).users(search,offset,limit)

    @app.patch('/api/admin/users/{user_id}')
    def admin_user_state(user_id:str,payload:AdminUserState,request:Request,user=Depends(admin_mutation)):
        return admin_call(lambda:AdminStore(repository(request)).set_disabled(user['id'],user_id,payload.disabled))

    @app.get('/api/admin/orders')
    def admin_orders(request:Request,user=Depends(administrator),status:str=Query(default='pending',pattern=r'^(pending|approved|cancelled|rejected|all)$'),offset:int=Query(default=0,ge=0),limit:int=Query(default=30,ge=1,le=100)):
        result=AdminStore(repository(request)).orders(status,offset,limit)
        payments=Payments(repository(request)).order_payments([o['id'] for o in result['items']])
        for order in result['items']:order['payment']=payments.get(order['id'])
        return result

    @app.get('/api/admin/telegram')
    def admin_telegram(request:Request,user=Depends(administrator)):
        return Telegram(repository(request)).status()

    @app.put('/api/admin/telegram')
    def admin_telegram_settings(payload:TelegramSettings,request:Request,user=Depends(admin_mutation)):
        step_up(request,user,payload.totp)
        try:return Telegram(repository(request)).configure(user['id'],payload.token)
        except PermissionError:raise HTTPException(403,'Administrator required')
        except TelegramError:raise HTTPException(502,'Telegram rejected the token or could not be reached')
        except ValueError as exc:raise HTTPException(422,str(exc))

    @app.post('/api/admin/telegram/broadcast')
    def admin_telegram_broadcast(payload:TelegramBroadcast,request:Request,user=Depends(admin_mutation)):
        try:return Telegram(repository(request)).broadcast(user['id'],payload.text)
        except PermissionError:raise HTTPException(403,'Administrator required')
        except ValueError as exc:raise HTTPException(422,str(exc))

    def referral_call(function):
        try:return function()
        except PermissionError:raise HTTPException(403,'Administrator required')
        except LookupError as exc:raise HTTPException(404,str(exc))
        except ReferralConflict as exc:raise HTTPException(409,str(exc))
        except ValueError as exc:raise HTTPException(422,str(exc))

    @app.get('/api/admin/referrals')
    def admin_referrals(request:Request,user=Depends(administrator)):
        return Referrals(repository(request)).admin_overview()

    @app.put('/api/admin/referrals/settings')
    def admin_referral_settings(payload:ReferralSettings,request:Request,user=Depends(admin_mutation)):
        return referral_call(lambda:Referrals(repository(request)).save_settings(user['id'],payload.model_dump()))

    @app.post('/api/admin/referrals/programs',status_code=201)
    def admin_referral_create(payload:ReferralProgram,request:Request,user=Depends(admin_mutation)):
        return referral_call(lambda:Referrals(repository(request)).save_program(user['id'],None,**payload.model_dump()))

    @app.put('/api/admin/referrals/programs/{program_id}')
    def admin_referral_update(program_id:str,payload:ReferralProgram,request:Request,user=Depends(admin_mutation)):
        return referral_call(lambda:Referrals(repository(request)).save_program(user['id'],program_id,**payload.model_dump()))

    @app.delete('/api/admin/referrals/programs/{program_id}')
    def admin_referral_delete(program_id:str,request:Request,user=Depends(admin_mutation)):
        return referral_call(lambda:Referrals(repository(request)).delete_program(user['id'],program_id))

    @app.post('/api/admin/referrals/codes',status_code=201)
    def admin_referral_code_create(payload:AdminReferralCode,request:Request,user=Depends(admin_mutation)):
        return referral_call(lambda:Referrals(repository(request)).save_code(user['id'],payload.code,payload.owner,payload.program_id,payload.label,payload.max_uses,payload.active,True))

    @app.put('/api/admin/referrals/codes/{code}')
    def admin_referral_code_update(code:str,payload:AdminReferralCode,request:Request,user=Depends(admin_mutation)):
        if payload.code.upper()!=code.upper():raise HTTPException(422,'Code mismatch')
        return referral_call(lambda:Referrals(repository(request)).save_code(user['id'],code,None,payload.program_id,payload.label,payload.max_uses,payload.active,False))

    @app.post('/api/admin/referrals/rewards',status_code=201)
    def admin_referral_grant(payload:ReferralGrant,request:Request,user=Depends(admin_mutation)):
        step_up(request,user,payload.totp)
        return referral_call(lambda:Referrals(repository(request)).grant(user['id'],payload.username,payload.kind,payload.value,payload.note,payload.expiry_days))

    @app.post('/api/admin/referrals/rewards/{reward_id}/release')
    def admin_referral_release(reward_id:str,request:Request,user=Depends(admin_mutation)):
        return referral_call(lambda:Referrals(repository(request)).release_held(user['id'],reward_id))

    @app.post('/api/admin/referrals/rewards/{reward_id}/void')
    def admin_referral_void(reward_id:str,request:Request,user=Depends(admin_mutation)):
        return referral_call(lambda:Referrals(repository(request)).void(user['id'],reward_id))

    @app.get('/api/admin/payments')
    def admin_payments(request:Request,user=Depends(administrator)):
        payments=Payments(repository(request))
        return {'settings':payments.admin_settings(),'transfers':payments.transfers()}

    @app.post('/api/admin/payments/transfers/attach')
    def admin_attach_transfer(payload:TransferAttach,request:Request,user=Depends(admin_mutation)):
        try:return Payments(repository(request)).attach_transfer(user['id'],payload.tx_ref,payload.order_id)
        except PermissionError:raise HTTPException(403,'Administrator required')
        except LookupError:raise HTTPException(404,'Record not found')
        except PaymentConflict as exc:raise HTTPException(409,str(exc))
        except ValueError as exc:raise HTTPException(422,str(exc))

    @app.put('/api/admin/payments')
    def admin_payment_settings(payload:PaymentSettings,request:Request,user=Depends(admin_mutation)):
        step_up(request,user,payload.totp)
        try:return Payments(repository(request)).save_settings(user['id'],payload.model_dump(exclude={'totp'}))
        except PermissionError:raise HTTPException(403,'Administrator required')
        except ValueError as exc:raise HTTPException(422,str(exc))

    @app.post('/api/admin/orders/{order_id}/reject')
    def admin_reject(order_id:str,payload:AdminRejection,request:Request,user=Depends(admin_mutation)):
        if not payload.reason.strip():raise HTTPException(422,'Reason required')
        return admin_call(lambda:AdminStore(repository(request)).reject(user['id'],order_id,payload.reason.strip()))

    @app.post('/api/admin/orders/{order_id}/refund')
    def admin_refund(order_id:str,payload:AdminRefund,request:Request,user=Depends(admin_mutation)):
        return admin_call(lambda:AdminStore(repository(request)).refund(user['id'],order_id,payload.refund_ref))

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

    def blog_call(function):
        try:return admin_call(function)
        except BlogConflict as exc:raise HTTPException(409,str(exc))

    @app.get('/api/admin/blog')
    def admin_blog(request:Request,user=Depends(administrator)):
        return {'items':BlogStore(repository(request)).all()}

    @app.get('/api/admin/blog/images')
    def admin_blog_images(request:Request,user=Depends(administrator)):
        return {'items':BlogStore(repository(request)).images()}

    @app.post('/api/admin/blog/images',status_code=201)
    async def admin_blog_upload(request:Request,user=Depends(admin_mutation),name:str=Query(default='',max_length=200)):
        if not request.headers.get('Content-Type','').startswith('image/'):raise HTTPException(415,'Upload a JPEG, PNG, WebP or GIF image')
        body=await request.body()
        try:return BlogStore(repository(request)).add_image(user['id'],body,name)
        except PermissionError:raise HTTPException(403,'Administrator required')
        except ValueError:raise HTTPException(422,'Not a readable JPEG, PNG, WebP or GIF image of at most 10 MB')

    @app.delete('/api/admin/blog/images/{image_id}')
    def admin_blog_image_delete(image_id:str,request:Request,user=Depends(admin_mutation)):
        return blog_call(lambda:BlogStore(repository(request)).delete_image(user['id'],image_id))

    @app.get('/api/admin/blog/{post_id}')
    def admin_blog_post(post_id:str,request:Request,user=Depends(administrator)):
        return admin_call(lambda:BlogStore(repository(request)).get(post_id))

    @app.post('/api/admin/blog',status_code=201)
    def admin_blog_create(payload:BlogArticle,request:Request,user=Depends(admin_mutation)):
        return blog_call(lambda:BlogStore(repository(request)).save(user['id'],payload.model_dump()))

    @app.put('/api/admin/blog/{post_id}')
    def admin_blog_update(post_id:str,payload:BlogArticle,request:Request,user=Depends(admin_mutation)):
        if payload.expected_updated is None:raise HTTPException(422,'expected_updated required')
        return blog_call(lambda:BlogStore(repository(request)).save(user['id'],payload.model_dump(),post_id,payload.expected_updated))

    @app.delete('/api/admin/blog/{post_id}')
    def admin_blog_delete(post_id:str,request:Request,user=Depends(admin_mutation),expected_updated:float=Query()):
        return blog_call(lambda:BlogStore(repository(request)).delete(user['id'],post_id,expected_updated))

    @app.get('/api/admin/audit')
    def admin_events(request:Request,user=Depends(administrator),offset:int=Query(default=0,ge=0),limit:int=Query(default=30,ge=1,le=100)):
        return AdminStore(repository(request)).events(offset,limit)

    def forward(request:Request):
        service=request.app.state.forward
        if service is None:raise HTTPException(404,'Not available')
        return service

    @app.get('/api/forward-test')
    def forward_test(request:Request):
        service=request.app.state.forward
        return service.summary() if service else {'available':False}

    @app.get('/api/admin/site-info')
    def admin_site_info(request:Request,user=Depends(administrator)):
        return portal_site.read(repository(request))

    @app.put('/api/admin/site-info')
    def admin_site_info_save(payload:SiteInfo,request:Request,user=Depends(admin_mutation)):
        try:values=portal_site.save(repository(request),user['id'],payload.model_dump())
        except PermissionError:raise HTTPException(403,'Administrator required')
        except ValueError as exc:raise HTTPException(422,str(exc))
        portal_blog.GENERATION[0]+=1
        return values

    @app.get('/api/admin/forward-test')
    def admin_forward_test(request:Request,user=Depends(administrator)):
        return forward(request).admin_status()

    @app.put('/api/admin/forward-test')
    def admin_forward_switch(payload:ForwardSwitch,request:Request,user=Depends(admin_mutation)):
        try:forward(request).set_hidden(user['id'],payload.hidden);portal_blog.GENERATION[0]+=1
        except PermissionError:raise HTTPException(403,'Administrator required')
        return forward(request).admin_status()

    @app.get('/robots.txt')
    def robots_file():return Response(robots_txt(origin),media_type='text/plain; charset=utf-8')

    @app.get('/sitemap.xml')
    def sitemap(request:Request):
        def build():
            posts={lang:blog_posts(request,lang) for lang in ('fa','en')}
            service=request.app.state.forward
            skip=();dates={}
            if service is not None:
                status=service.summary()
                if service.hidden():skip=('/forward-test/','/en/forward-test/')
                elif status.get('data_through'):dates={'/forward-test/':status['data_through']}
            return sitemap_xml(origin,frontend,posts,extra=SERVER_PAGES,skip=skip,dates=dates)
        return Response(cached_page(('sitemap',),build),media_type='application/xml')

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

    # Referrals: a personal invite code, what it earns, and credit/coupons for purchases.
    @app.get('/api/referral/{code}')
    def referral_lookup(code:str,request:Request):
        if len(code)>24:raise HTTPException(404,'Unknown code')
        client=request.client.host if request.client else 'unknown'
        if not repository(request).attempt('referral-lookup:'+client,limit=30):raise HTTPException(429,'Too many lookups')
        return Referrals(repository(request)).lookup(code)

    @app.get('/api/me/referral')
    def referral_account(request:Request,user=Depends(identity)):
        return Referrals(repository(request)).account(user['id'])

    @app.put('/api/me/referral/code')
    def referral_code(payload:ReferralCode,request:Request,user=Depends(mutation)):
        try:return Referrals(repository(request)).set_code(user['id'],payload.code)
        except ReferralConflict as exc:raise HTTPException(409,str(exc))
        except ValueError as exc:raise HTTPException(422,str(exc))

    @app.post('/api/me/referral/attach')
    def referral_attach(payload:ReferralCode,request:Request,user=Depends(mutation)):
        try:return Referrals(repository(request)).attach_later(user['id'],payload.code)
        except ReferralConflict as exc:raise HTTPException(409,str(exc))
        except ValueError as exc:raise HTTPException(422,str(exc))

    # Telegram: link this account to the site's bot to receive signals and notices there.
    @app.get('/api/me/telegram')
    def telegram_account(request:Request,user=Depends(identity)):
        return Telegram(repository(request)).account(user['id'])

    @app.post('/api/me/telegram/link')
    def telegram_link(payload:TelegramLink,request:Request,user=Depends(mutation)):
        try:return Telegram(repository(request)).link_code(user['id'],payload.lang)
        except LookupError:raise HTTPException(409,'Telegram is not set up yet')

    @app.put('/api/me/telegram')
    def telegram_preferences(payload:TelegramPreferences,request:Request,user=Depends(mutation)):
        try:return Telegram(repository(request)).preferences(user['id'],payload.signals,payload.notices)
        except LookupError:raise HTTPException(409,'Telegram is not linked')

    @app.delete('/api/me/telegram')
    def telegram_unlink(request:Request,user=Depends(mutation)):
        return Telegram(repository(request)).unlink(user['id'])

    # Pay an order in USDT/USDC directly to the owner's wallet; the payment watcher confirms it on-chain.
    @app.get('/api/me/payment-methods')
    def payment_methods(request:Request,user=Depends(identity)):
        return {'methods':Payments(repository(request)).methods()}

    @app.post('/api/me/license/orders/{order_id}/invoice')
    def create_invoice(order_id:str,payload:InvoiceRequest,request:Request,user=Depends(mutation)):
        try:return Payments(repository(request)).create_invoice(user['id'],order_id,payload.network,payload.token)
        except PaymentConflict as exc:raise HTTPException(409,str(exc))
        except ValueError:raise HTTPException(422,'Unknown payment method')

    @app.get('/api/me/license/orders/{order_id}/invoice')
    def read_invoice(order_id:str,request:Request,user=Depends(identity)):
        invoice=Payments(repository(request)).invoice(user['id'],order_id)
        if not invoice:raise HTTPException(404,'No invoice for this order')
        return invoice

    @app.post('/api/me/license/orders/{order_id}/cancel')
    def cancel_license(order_id:str,request:Request,user=Depends(mutation)):
        try:Billing(repository(request)).cancel(user['id'],order_id)
        except PaidOrderConflict as exc:raise HTTPException(409,str(exc))
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

    @app.get('/api/register/token')
    def register_token(request:Request):
        store=repository(request)
        if not store.attempt('signup-token:'+(request.client.host if request.client else 'unknown')):raise HTTPException(429,'Too many requests')
        return {'token':store.form_token()}

    @app.post('/api/register',status_code=201)
    def register(payload:Registration,request:Request,response:Response):
        same_origin(request)
        store=repository(request)
        client=request.client.host if request.client else 'unknown'
        if not store.attempt('signup:'+client):raise HTTPException(429,'Too many signup attempts')
        # Bots fill the hidden field or submit instantly; both get the same answer as any other invalid form.
        if payload.website or not store.form_token_valid(payload.form_token):
            raise HTTPException(422,'Invalid fields; check input length and required fields')
        password=payload.password.get_secret_value()
        if not secrets.compare_digest(password.encode(),payload.password_confirmation.get_secret_value().encode()):
            raise HTTPException(422,'Password confirmation does not match')
        try:token,csrf=store.register(payload.username,password,payload.email,(payload.referral_code or '').strip() or None)
        except EmailTaken:raise HTTPException(409,'Username or email unavailable')
        except ReferralConflict as exc:raise HTTPException(409,str(exc))
        except ValueError as exc:
            if 'referral' in str(exc).lower():raise HTTPException(422,'Invalid referral code')
            if str(exc)=='Invalid email':raise HTTPException(422,'Invalid email')
            raise HTTPException(409,'Username or email unavailable')  # One answer for both, so neither can be probed.
        store.logout(request.cookies.get(COOKIE,''))
        set_session_cookie(response,token,'customer')
        queue_verification(store,payload.username,payload.email,payload.lang)
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
        try:session=store.login(payload.username,payload.password.get_secret_value(),payload.totp)
        except LoginLocked as exc:
            raise HTTPException(429,'Too many failed attempts for this account; try again later',headers={'Retry-After':str(exc.wait)})
        except TwoFactorRequired:raise HTTPException(401,'Two-factor code required')
        if not session:raise HTTPException(401,'Invalid credentials')
        # Rotation invalidates an already logged-in session for this browser.
        store.logout(request.cookies.get(COOKIE,''))
        token,csrf=session
        set_session_cookie(response,token,store.session(token)['role'])
        return {'csrf':csrf}

    @app.post('/api/logout')
    def logout(request:Request,response:Response,user=Depends(mutation)):
        repository(request).logout(request.cookies.get(COOKIE,''))
        response.delete_cookie(COOKIE,path='/',secure=secure,httponly=True,samesite='strict')
        return {'status':'logged_out'}

    @app.get('/api/me')
    def me(request:Request,user=Depends(identity)):
        with repository(request).db() as db:mail_on=portal_mail.enabled(db)
        return dict(username=user['username'],email=user.get('email'),email_verified=user['email_verified'],mail_enabled=mail_on,
                    csrf=user['csrf'],role=user['role'],totp_enabled=user['totp_enabled'],live_execution_supported=False)

    @app.put('/api/me/email')
    def change_email(payload:EmailChange,request:Request,user=Depends(mutation)):
        reauthenticate(request,user,payload.current_password)
        try:email=repository(request).set_email(user['id'],payload.email)
        except EmailTaken:raise HTTPException(409,'Email unavailable')
        except ValueError:raise HTTPException(422,'Invalid email')
        if email!=user.get('email'):queue_verification(repository(request),user['id'],email,payload.lang,False)
        return {'email':email}

    @app.post('/api/me/email/verify',status_code=202)
    def resend_verification(payload:VerifyResend,request:Request,user=Depends(mutation)):
        store=repository(request)
        if not store.attempt('verify-resend:'+user['id'],limit=5):raise HTTPException(429,'Too many requests; retry in one minute')
        try:queued=portal_mail.resend_verification(store,user['id'],origin,payload.lang)
        except LookupError:raise HTTPException(409,'Nothing to verify')
        except portal_mail.Cooldown:raise HTTPException(429,'A link was just sent; wait a minute',headers={'Retry-After':'60'})
        if not queued:raise HTTPException(409,'Email is not enabled on this site')
        return {'status':'queued'}

    @app.put('/api/me/password')
    def change_password(payload:PasswordChange,request:Request,response:Response,user=Depends(mutation)):
        new=payload.new_password.get_secret_value()
        if not secrets.compare_digest(new.encode(),payload.new_password_confirmation.get_secret_value().encode()):
            raise HTTPException(422,'Password confirmation does not match')
        reauthenticate(request,user,payload.current_password)
        token,csrf=repository(request).change_password(user['id'],new)
        set_session_cookie(response,token,user['role'])
        return {'csrf':csrf}

    @app.post('/api/me/sessions/revoke-others')
    def revoke_other_sessions(request:Request,user=Depends(mutation)):
        return {'revoked':repository(request).revoke_others(user['id'],request.cookies.get(COOKIE,''))}

    # Recovery without email: a one-time code goes to the Telegram chat linked to the account.
    @app.post('/api/password-reset/request',status_code=202)
    def reset_request(payload:ResetRequest,request:Request):
        same_origin(request)
        store=repository(request)
        client=request.client.host if request.client else 'unknown'
        if not store.attempt('reset:'+client) or not store.attempt('reset-user:'+payload.username):
            raise HTTPException(429,'Too many attempts; retry in one minute')
        portal_security.request_reset(store,payload.username)
        return {'status':'If the account exists and has Telegram linked, a code was sent there'}

    @app.post('/api/password-reset/confirm')
    def reset_confirm(payload:ResetConfirm,request:Request):
        same_origin(request)
        store=repository(request)
        client=request.client.host if request.client else 'unknown'
        if not store.attempt('reset:'+client) or not store.attempt('reset-user:'+payload.username):
            raise HTTPException(429,'Too many attempts; retry in one minute')
        new=payload.new_password.get_secret_value()
        if not secrets.compare_digest(new.encode(),payload.new_password_confirmation.get_secret_value().encode()):
            raise HTTPException(422,'Password confirmation does not match')
        if not portal_security.confirm_reset(store,payload.username,payload.code,new):raise HTTPException(403,'Invalid or expired code')
        return {'status':'password_changed'}

    @app.post('/api/me/totp/setup')
    def totp_setup(payload:TotpSetup,request:Request,user=Depends(mutation)):
        reauthenticate(request,user,payload.current_password)
        try:return portal_security.setup(repository(request),user['id'])
        except portal_security.SecurityConflict as exc:raise HTTPException(409,str(exc))

    @app.post('/api/me/totp/enable')
    def totp_enable(payload:TotpEnable,request:Request,user=Depends(mutation)):
        throttled(request,user)
        try:codes=portal_security.enable(repository(request),user['id'],payload.code)
        except portal_security.SecurityConflict as exc:raise HTTPException(409,str(exc))
        if codes is None:raise HTTPException(403,'Invalid two-factor code')
        return {'recovery_codes':codes}

    @app.post('/api/me/totp/disable')
    def totp_disable(payload:TotpDisable,request:Request,user=Depends(mutation)):
        reauthenticate(request,user,payload.current_password)
        if not portal_security.disable(repository(request),user['id'],payload.code):raise HTTPException(403,'Invalid two-factor code')
        return {'status':'disabled'}

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
        if payload.exchange_id not in PERMISSION_CHECKS and not payload.no_withdrawal_ack:
            raise HTTPException(422,'Confirm that this key has no withdrawal permission')
        repository(request).save_connection(user['id'],payload.market,
                                            payload.api_key.get_secret_value(),payload.secret.get_secret_value(),payload.exchange_id,phrase,uid,
                                            payload.no_withdrawal_ack and payload.exchange_id not in PERMISSION_CHECKS)
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

    @app.get('/api/me/execution-readiness')
    def execution_readiness(request:Request,user=Depends(identity)):
        from portal_execution import readiness
        store=repository(request)
        return readiness(store.public_connection(user['id']),Billing(store).snapshot(user['id'])['license'])

    @app.get('/api/me/robots')
    def robot_status(user=Depends(identity)):
        return {'robots':robots(user['runtime'],user['username']),'live_execution_supported':False}

    @app.get('/verify-email',response_class=HTMLResponse)
    @app.get('/en/verify-email',response_class=HTMLResponse)
    def verify_email(request:Request,token:str=Query(default='',max_length=100)):
        lang=page_lang(request.url.path)
        done=portal_mail.verify(repository(request),token)
        fa=lang=='fa'
        page=portal_blog.notice_page(
            origin,site_css(),lang,('/en' if lang=='en' else '')+'/verify-email',
            ('ایمیل تأیید شد' if fa else 'Email confirmed') if done else ('پیوند نامعتبر است' if fa else 'Link not valid'),
            ('ایمیل شما تأیید شد' if fa else 'Your email is confirmed') if done else ('این پیوند معتبر نیست' if fa else 'This link is not valid'),
            ('ایمیل حساب آوینای شما تأیید شد.' if fa else 'The email address of your Avina account is confirmed.') if done else
            ('پیوند منقضی شده یا قبلاً استفاده شده است. از پنل خود پیوند تازه‌ای بخواهید.' if fa else 'The link has expired or was already used. Ask for a new one in your panel.'),
            (('/en' if lang=='en' else '')+'/dashboard/','Dashboard' if not fa else 'ورود به پنل'))
        return HTMLResponse(page,status_code=200 if done else 400)

    # Any other address a browser might open gets the site's own 404 page. API and static paths keep their JSON/plain answers.
    @app.api_route('/{unknown:path}',methods=['GET','POST','PUT','PATCH','DELETE'],response_class=HTMLResponse,include_in_schema=False)
    def unknown_page(unknown:str,request:Request):
        path=request.url.path
        for route in app.router.routes:
            # A real route that only lacks this method keeps answering 405, as before.
            if route.matches(request.scope)[0]==Match.PARTIAL and route.endpoint is not unknown_page:
                raise HTTPException(405,'Method Not Allowed',headers={'Allow':', '.join(sorted(route.methods))})
        if request.method!='GET' or path=='/api' or path.startswith(NOT_PAGES):raise HTTPException(404,'Not Found')
        return not_found(request)

    return app


def main():
    import uvicorn
    proxies=trusted_proxies(os.getenv('PORTAL_TRUSTED_PROXY_IPS',''))
    uvicorn.run(create_app(),host=os.getenv('PORTAL_HOST','127.0.0.1'),port=int(os.getenv('PORTAL_PORT','8080')),
                proxy_headers=bool(proxies),forwarded_allow_ips=proxies,access_log=False)


if __name__=='__main__':main()
