"""Central account portal pilot, separate from the single-customer bot dashboard."""
from contextlib import asynccontextmanager
import os
import ipaddress
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from portal_store import EmailTaken, PortalStore
from portal_database import configured_target
from portal_jobs import AccountQueue,MissingConnection,RefreshLimited,QueueFull
from portal_runtime import robots
from portal_exchanges import catalog,validate_connection,UnsupportedAccount
from portal_billing import Billing, BillingConflict
import product_pricing
from signal_feed import read_feed
from portal_frontend import frontend_index, private_page, public_file, public_page, robots_txt, sitemap_xml
import portal_blog
from portal_blog import BlogConflict, BlogStore
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
    email:str=Field(min_length=6,max_length=254)


class EmailChange(BaseModel):
    model_config=ConfigDict(extra='forbid')
    email:str=Field(min_length=6,max_length=254)


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


class BlogArticle(BaseModel):
    model_config=ConfigDict(extra='forbid')
    lang:str=Field(default='fa',pattern=r'^(fa|en)$')
    slug:str=Field(min_length=1,max_length=80,pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
    title:str=Field(min_length=1,max_length=120)
    description:str=Field(min_length=1,max_length=300)
    keywords:list[str]=Field(default_factory=list,max_length=20)
    body:str=Field(min_length=1,max_length=60000)
    status:str=Field(pattern=r'^(draft|published)$')
    published_on:str|None=Field(default=None,pattern=r'^\d{4}-\d{2}-\d{2}$')
    expected_updated:float|None=None


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
        if hasattr(app.state.store,'database'):BlogStore(app.state.store).seed()
        try:yield
        finally:
            if supplied_store is None:app.state.store.close()

    app=FastAPI(title='Trade customer portal',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=[parsed.hostname])
    frontend=Path(os.getenv('PORTAL_FRONTEND_DIR',str(Path(__file__).with_name('frontend')/'out')))
    public=Path(__file__).with_name('frontend')/'public'
    page_files={'/':'index.html','/register':'register.html','/register/':'register.html','/admin':'admin.html','/admin/':'admin.html','/dashboard':'dashboard.html','/dashboard/':'dashboard.html',
                '/en':'en.html','/en/':'en.html','/en/register':'en/register.html','/en/register/':'en/register.html',
                '/en/admin':'en/admin.html','/en/admin/':'en/admin.html','/en/dashboard':'en/dashboard.html','/en/dashboard/':'en/dashboard.html'}
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

    def blog_posts(request,lang='fa'):
        store=repository(request)
        return BlogStore(store).published(lang) if hasattr(store,'database') else []

    def site_css():
        try:return portal_blog.stylesheets(frontend_index(frontend)[0])
        except OSError:return []

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
        response=await call_next(request)
        path=request.url.path
        blog_page=path in ('/blog','/en/blog') or path.startswith(('/blog/','/en/blog/'))
        public=public_file(path) or blog_page and response.status_code==200
        page=page_files.get(path) or (public[1] if isinstance(public,tuple) else None)
        if response.status_code==404 and blog_page:page='404.html'
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
        elif public:cache='no-cache'
        else:
            cache='no-store'
            response.headers['X-Robots-Tag']='noindex, nofollow'
        if response.status_code>=400:cache='no-store'
        response.headers.update({'Cache-Control':cache,'X-Content-Type-Options':'nosniff',
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

    def not_built():
        return HTMLResponse('Next.js frontend is not built. Run npm ci and npm run build in lbank_project/frontend.',status_code=503)

    def not_found():
        try:return HTMLResponse(frontend_index(frontend,'404.html')[0],status_code=404)
        except OSError:return HTMLResponse('Not found',status_code=404)

    # Public pages in both languages.
    @app.get('/',response_class=HTMLResponse)
    @app.get('/en',response_class=HTMLResponse)
    @app.get('/en/',response_class=HTMLResponse)
    @app.get('/register',response_class=HTMLResponse)
    @app.get('/register/',response_class=HTMLResponse)
    @app.get('/en/register',response_class=HTMLResponse)
    @app.get('/en/register/',response_class=HTMLResponse)
    def public_pages(request:Request):
        try:return HTMLResponse(public_page(frontend,request.url.path,origin))
        except OSError:return not_built()

    # Signed-in pages: the client checks the session; the server serves the same shell to everyone.
    @app.get('/dashboard',response_class=HTMLResponse)
    @app.get('/dashboard/',response_class=HTMLResponse)
    @app.get('/admin',response_class=HTMLResponse)
    @app.get('/admin/',response_class=HTMLResponse)
    @app.get('/en/dashboard',response_class=HTMLResponse)
    @app.get('/en/dashboard/',response_class=HTMLResponse)
    @app.get('/en/admin',response_class=HTMLResponse)
    @app.get('/en/admin/',response_class=HTMLResponse)
    def private_pages(request:Request):
        try:return HTMLResponse(private_page(frontend,page_files[request.url.path]))
        except OSError:return not_built()

    @app.get('/blog/rss.xml')
    @app.get('/en/blog/rss.xml')
    def blog_feed(request:Request):
        lang='en' if request.url.path.startswith('/en/') else 'fa'
        return Response(portal_blog.rss_xml(origin,blog_posts(request,lang),lang),media_type='application/rss+xml; charset=utf-8')

    @app.get('/blog',response_class=HTMLResponse)
    @app.get('/blog/',response_class=HTMLResponse)
    @app.get('/en/blog',response_class=HTMLResponse)
    @app.get('/en/blog/',response_class=HTMLResponse)
    def blog_index(request:Request):
        lang='en' if request.url.path.startswith('/en/') else 'fa'
        return HTMLResponse(portal_blog.index_page(origin,site_css(),blog_posts(request,lang),lang))

    @app.get('/blog/{slug}',response_class=HTMLResponse)
    @app.get('/blog/{slug}/',response_class=HTMLResponse)
    @app.get('/en/blog/{slug}',response_class=HTMLResponse)
    @app.get('/en/blog/{slug}/',response_class=HTMLResponse)
    def blog_article(slug:str,request:Request):
        lang='en' if request.url.path.startswith('/en/') else 'fa'
        store=repository(request)
        if not hasattr(store,'database'):return not_found()
        blog=BlogStore(store);post=blog.article(slug,lang)
        if not post:return not_found()
        related=[item for item in blog_posts(request,lang) if item['slug']!=post['slug']][:2]
        sizes=blog.image_sizes(portal_blog.image_ids(post['body']))
        return HTMLResponse(portal_blog.article_page(origin,site_css(),post,related,blog.translations(slug),lang,sizes))

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

    @app.get('/api/admin/users')
    def admin_users(request:Request,user=Depends(administrator),search:str=Query(default='',max_length=80),offset:int=Query(default=0,ge=0),limit:int=Query(default=30,ge=1,le=100)):
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

    @app.get('/robots.txt')
    def robots_file():return Response(robots_txt(origin),media_type='text/plain; charset=utf-8')

    @app.get('/sitemap.xml')
    def sitemap(request:Request):
        posts={lang:blog_posts(request,lang) for lang in ('fa','en')}
        return Response(sitemap_xml(origin,frontend,posts),media_type='application/xml')

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
        try:token,csrf=store.register(payload.username,password,payload.email)
        except EmailTaken:raise HTTPException(409,'Email unavailable')
        except ValueError as exc:
            if 'email' in str(exc).lower():raise HTTPException(422,'Invalid email')
            raise HTTPException(409,'Username unavailable')
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
        return dict(username=user['username'],email=user.get('email'),csrf=user['csrf'],role=user['role'],live_execution_supported=False)

    @app.put('/api/me/email')
    def change_email(payload:EmailChange,request:Request,user=Depends(mutation)):
        try:return {'email':repository(request).set_email(user['id'],payload.email)}
        except EmailTaken:raise HTTPException(409,'Email unavailable')
        except ValueError:raise HTTPException(422,'Invalid email')

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

    @app.get('/api/me/execution-readiness')
    def execution_readiness(request:Request,user=Depends(identity)):
        from portal_execution import readiness
        store=repository(request)
        return readiness(store.public_connection(user['id']),Billing(store).snapshot(user['id'])['license'])

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
