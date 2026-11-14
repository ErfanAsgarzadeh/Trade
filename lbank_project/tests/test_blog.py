"""Blog: admin-written articles, safe rendering, publication states and search metadata."""
import json
import re

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

import portal_blog
from portal_blog import BlogStore, persian_date, render_body
from portal_server import create_app
from portal_store import PortalStore

ORIGIN='https://avina.example';PASSWORD='disposable-test-password'
BODY='## بخش اول\nمتن با **تأکید** و [پیوند](/blog/other/).\n\n## بخش دوم\n- یک\n- دو\n\n## بخش سوم\n> نقل قول'


@pytest.fixture
def store(tmp_path):
    store=PortalStore(tmp_path/'portal.db',Fernet.generate_key())
    store.create_user('manager',PASSWORD);store.set_admin('manager');store.create_user('alice',PASSWORD)
    yield store
    store.close()


def login(client,name='manager'):
    response=client.post('/api/login',headers={'X-Portal-Request':'1','Origin':ORIGIN},json=dict(username=name,password=PASSWORD))
    assert response.status_code==200,response.text
    return {'X-Portal-Request':'1','Origin':ORIGIN,'X-CSRF-Token':response.json()['csrf']}


def article(**fields):
    return dict(dict(slug='new-guide',title='راهنمای تازهٔ ربات ترید',description='توضیح کوتاه مقاله',keywords=['ربات ترید'],
                     body=BODY,status='published'),**fields)


def test_markdown_escapes_html_and_drops_unsafe_links():
    html=render_body('<script>alert(1)</script>\n\n[x](javascript:alert) [y](//evil.example) [z](https://ok.example/a) [w](/blog/a/)\n\n## <b>تیتر</b>')
    assert '<script>' not in html and '&lt;script&gt;' in html and '<b>' not in html
    assert 'javascript:' not in html and '//evil.example' not in html
    assert '<a href="https://ok.example/a" rel="noopener" target="_blank">z</a>' in html and '<a href="/blog/a/">w</a>' in html
    assert re.search(r'<h2 id="[^"]+">&lt;b&gt;تیتر&lt;/b&gt;</h2>',html)
    assert render_body('## الف\n## الف').count('id="الف-2"')==1


def test_persian_dates_follow_the_solar_hijri_calendar():
    assert persian_date('2026-11-13')=='۲۲ آبان ۱۴۰۵'
    assert persian_date('2025-03-21')=='۱ فروردین ۱۴۰۴'
    assert persian_date('2024-03-19')=='۲۹ اسفند ۱۴۰۲'


def test_launch_articles_are_imported_once_and_deletions_stick(store):
    blog=BlogStore(store)
    seeded=blog.seed()
    assert seeded>=10 and len(blog.published('fa'))+len(blog.published('en'))==seeded
    assert {p['slug'] for p in blog.published('fa')}=={p['slug'] for p in blog.published('en')}
    victim=blog.all()[0]
    with store.db() as db:actor=db.execute("SELECT id FROM users WHERE username='manager'").fetchone()['id']
    blog.delete(actor,victim['id'],victim['updated'])
    assert blog.seed()==0 and len(blog.all())==seeded-1


def test_launch_articles_do_not_describe_the_trading_method(store):
    blog=BlogStore(store);blog.seed()
    text=' '.join(blog.get(p['id'])['body'] for p in blog.all())
    for word in ('Donchian','Ichimoku','ایچیموکو','پولبک','شکست روند','RSI','EMA'):
        assert word not in text,word


def test_old_launch_article_text_is_fixed_once_without_touching_edits(store):
    import uuid,time,json as j
    old=portal_blog.CONTENT_FIXES[0][2]
    with store.db() as db:
        db.execute('INSERT INTO blog_posts(id,lang,slug,title,description,keywords,body,status,published_on,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (str(uuid.uuid4()),'fa','what-is-a-trading-bot','t','d',j.dumps([]),'intro '+old,'published','2026-11-13',time.time(),time.time()))
        db.execute("INSERT INTO service_gate(name,next_at) VALUES('blog:seeded',0)")
    blog=BlogStore(store);blog.seed()
    body=blog.article('what-is-a-trading-bot','fa')['body']
    assert old not in body and portal_blog.CONTENT_FIXES[0][3] in body


def test_admin_writes_drafts_publishes_schedules_and_deletes(store):
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        assert client.get('/api/admin/blog').status_code==401
        customer=login(client,'alice')
        assert client.get('/api/admin/blog').status_code==403
        assert client.post('/api/admin/blog',headers=customer,json=article()).status_code==403
        headers=login(client)
        assert client.post('/api/admin/blog',json=article()).status_code==403  # no CSRF token
        draft=client.post('/api/admin/blog',headers=headers,json=article(status='draft'))
        assert draft.status_code==201 and draft.json()['published_on'] is None
        assert client.get('/blog/new-guide/').status_code==404
        assert client.post('/api/admin/blog',headers=headers,json=article(title='دیگر')).status_code==409  # address taken
        assert client.post('/api/admin/blog',headers=headers,json=article(slug='Bad Slug')).status_code==422
        post=draft.json()
        published=client.put('/api/admin/blog/'+post['id'],headers=headers,json=article(expected_updated=post['updated']))
        assert published.status_code==200 and published.json()['published_on']
        # A stale editor cannot overwrite the newer version.
        assert client.put('/api/admin/blog/'+post['id'],headers=headers,json=article(title='قدیمی',expected_updated=post['updated'])).status_code==409
        page=client.get('/blog/new-guide')
        assert page.status_code==200 and page.headers['cache-control']=='no-cache' and 'x-robots-tag' not in page.headers
        assert page.text.count('<h1')==1 and '"BlogPosting"' in page.text and '"BreadcrumbList"' in page.text
        assert '<link rel="canonical" href="https://avina.example/blog/new-guide/"/>' in page.text
        assert 'class="blog-contents"' in page.text and '<strong>تأکید</strong>' in page.text
        assert "script-src 'self' ;" in page.headers['content-security-policy']
        assert '<loc>https://avina.example/blog/new-guide/</loc>' in client.get('/sitemap.xml').text
        assert 'https://avina.example/blog/new-guide/' in client.get('/blog/rss.xml').text
        assert client.get('/api/blog/latest').json()['items'][0]['slug']=='new-guide'
        current=published.json()
        scheduled=client.put('/api/admin/blog/'+post['id'],headers=headers,json=article(published_on='2999-01-01',expected_updated=current['updated']))
        assert scheduled.status_code==200 and client.get('/blog/new-guide/').status_code==404
        assert 'new-guide' not in client.get('/sitemap.xml').text
        assert client.delete(f"/api/admin/blog/{post['id']}?expected_updated={scheduled.json()['updated']}",headers=headers).status_code==200
        actions=[e['action'] for e in client.get('/api/admin/audit').json()['items']]
        assert {'blog_created','blog_updated','blog_deleted'}<=set(actions)


def test_long_articles_fit_while_other_requests_keep_the_small_limit(store):
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        headers=login(client)
        long_body=BODY+'\n\n'+('متن بلند فارسی برای آزمون اندازهٔ درخواست. '*1000)
        assert len(json.dumps(article(body=long_body)).encode())>16384
        assert client.post('/api/admin/blog',headers=headers,json=article(body=long_body)).status_code==201
        assert client.post('/api/login',headers=headers,content=b'x'*20000).status_code==413


def test_public_blog_pages_seed_render_and_reject_unknown_addresses(store):
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        index=client.get('/blog')
        assert index.status_code==200 and '<link rel="canonical" href="https://avina.example/blog/"/>' in index.text
        assert index.text.count('class="blog-card"')>=5 and 'data-legacy-theme-switch' in index.text
        assert re.search(r'<link rel="stylesheet" href="/_next/static/css/[^"]+\.css"/>',index.text)
        for missing in ('/blog/not-a-post/','/blog/Upper/','/blog/a_b','/blog/..%2fadmin'):
            response=client.get(missing)
            assert response.status_code==404 and response.headers['x-robots-tag']=='noindex, nofollow'


def test_english_blog_pages_hreflang_and_feeds(store):
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        index=client.get('/en/blog/')
        assert index.status_code==200 and '<html lang="en" dir="ltr"' in index.text
        assert '<link rel="canonical" href="https://avina.example/en/blog/"/>' in index.text
        assert 'hreflang="fa" href="https://avina.example/blog/"' in index.text and 'Avina Blog' in index.text
        page=client.get('/en/blog/futures-stop-loss/')
        assert page.status_code==200 and '"inLanguage": "en"' in page.text
        assert 'hreflang="fa" href="https://avina.example/blog/futures-stop-loss/"' in page.text
        assert 'hreflang="en" href="https://avina.example/en/blog/futures-stop-loss/"' in page.text
        assert client.get('/blog/futures-stop-loss/').text.count('rel="alternate" hreflang="en"')==1
        assert client.get('/en/blog/no-such-post/').status_code==404
        assert client.get('/api/blog/latest?lang=en').json()['items'][0]['date_label'].startswith('November')
        assert client.get('/api/blog/latest?lang=de').status_code==422
        assert '<language>en</language>' in client.get('/en/blog/rss.xml').text
        sitemap=client.get('/sitemap.xml').text
        assert '<loc>https://avina.example/en/blog/futures-stop-loss/</loc>' in sitemap
        assert '<loc>https://avina.example/en/</loc>' in sitemap and '<loc>https://avina.example/en/register/</loc>' in sitemap
        headers=login(client)
        made=client.post('/api/admin/blog',headers=headers,json=article(lang='en',slug='futures-stop-loss'))
        assert made.status_code==409  # same address in the same language
        made=client.post('/api/admin/blog',headers=headers,json=article(lang='en',slug='english-only'))
        assert made.status_code==201 and made.json()['lang']=='en'
        assert client.get('/en/blog/english-only/').status_code==200 and client.get('/blog/english-only/').status_code==404


def test_english_site_pages_are_served_in_english(store):
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        for path in ('/en/','/en/register/','/en/dashboard/','/en/admin/'):
            page=client.get(path)
            assert page.status_code==200 and '<html lang="en" dir="ltr"' in page.text,path
            assert "'sha256-" in page.headers['content-security-policy']
        home=client.get('/en/')
        assert '<link rel="canonical" href="https://avina.example/en/"/>' in home.text
        assert 'hreflang="fa" href="https://avina.example/"' in home.text and 'hreflang="x-default"' in home.text
        assert client.get('/en/dashboard/').headers['x-robots-tag']=='noindex, nofollow'
        assert '<html lang="fa" dir="rtl"' in client.get('/').text
        assert 'hreflang="en" href="https://avina.example/en/"' in client.get('/').text


def jpeg_with_gps(width=2400,height=1200):
    import io
    from PIL import Image
    image=Image.new('RGB',(width,height),(120,40,200))
    exif=Image.Exif();exif[0x8825]={1:'N',2:(35.0,41.0,0.0)};exif[0x010F]='SecretCam'
    out=io.BytesIO();image.save(out,'JPEG',exif=exif.tobytes());return out.getvalue()


def test_uploaded_images_are_resized_reencoded_and_stripped_of_metadata():
    import io
    from PIL import Image
    data,width,height=portal_blog.process_image(jpeg_with_gps())
    assert (width,height)==(1600,800) and data[:4]==b'RIFF' and data[8:12]==b'WEBP'
    assert b'SecretCam' not in data and not Image.open(io.BytesIO(data)).getexif()
    for bad in (b'',b'not an image',b'<svg xmlns="http://www.w3.org/2000/svg"/>'):
        with pytest.raises(ValueError):portal_blog.process_image(bad)
    big=io.BytesIO();Image.new('L',(8000,6000)).save(big,'PNG')
    with pytest.raises(ValueError):portal_blog.process_image(big.getvalue())


def test_admin_uploads_images_places_them_anywhere_and_cannot_delete_used_ones(store):
    with TestClient(create_app(store,origin=ORIGIN),base_url=ORIGIN) as client:
        raw=jpeg_with_gps()
        assert client.post('/api/admin/blog/images',content=raw,headers={'Content-Type':'image/jpeg'}).status_code==401
        customer=login(client,'alice')
        assert client.post('/api/admin/blog/images',content=raw,headers={**customer,'Content-Type':'image/jpeg'}).status_code==403
        headers=login(client)
        assert client.post('/api/admin/blog/images',content=raw,headers={'Content-Type':'image/jpeg'}).status_code==403  # CSRF
        assert client.post('/api/admin/blog/images',content=raw,headers={**headers,'Content-Type':'text/plain'}).status_code==415
        assert client.post('/api/admin/blog/images',content=b'x',headers={**headers,'Content-Type':'image/png'}).status_code==422
        too_big=b'x'*(portal_blog.MAX_UPLOAD+1)
        assert client.post('/api/admin/blog/images',content=too_big,headers={**headers,'Content-Type':'image/png'}).status_code==413
        image=client.post('/api/admin/blog/images?name=chart%20<b>.jpg',content=raw,headers={**headers,'Content-Type':'image/jpeg'})
        assert image.status_code==201,image.text
        image=image.json();assert image['width']==1600 and '<' not in image['name']
        served=client.get(image['url'])
        assert served.status_code==200 and served.headers['content-type']=='image/webp'
        assert served.headers['cache-control']=='public, max-age=31536000, immutable' and served.content[8:12]==b'WEBP'
        assert client.get('/blog-media/ffffffffffffffffffffffff.webp').status_code==404
        assert client.get('/blog-media/..%2fportal.db').status_code==404
        body=('مقدمه با تصویر کوچک ![نماد]('+image['url']+') وسط متن.\n![نمودار رشد سرمایه]('+image['url']+' "زیرنویس نمودار")\n'
              'ادامه بلافاصله بعد از تصویر\n\n![خارجی](https://evil.example/x.webp)\n\n![گم‌شده](/blog-media/aaaaaaaaaaaaaaaaaaaaaaaa.webp)')
        post=client.post('/api/admin/blog',headers=headers,json=article(slug='with-image',body=body))
        assert post.status_code==201
        page=client.get('/blog/with-image/').text
        assert '<figure class="blog-figure"><img src="'+image['url']+'" alt="نمودار رشد سرمایه" width="1600" height="800"' in page
        assert '<figcaption>زیرنویس نمودار</figcaption>' in page and 'class="blog-inline-image"' in page
        assert 'evil.example' not in page and 'aaaaaaaaaaaaaaaaaaaaaaaa' not in page and '<p>ادامه بلافاصله بعد از تصویر</p>' in page
        assert '<meta property="og:image" content="https://avina.example'+image['url']+'"/>' in page
        assert '<meta property="og:image:width" content="1600"/>' in page
        library=client.get('/api/admin/blog/images').json()['items']
        assert library[0]['id']==image['id'] and library[0]['used_in'][0]['slug']=='with-image'
        assert client.delete('/api/admin/blog/images/'+image['id'],headers=headers).status_code==409
        post=post.json()
        client.put('/api/admin/blog/'+post['id'],headers=headers,json=article(slug='with-image',body='بدون تصویر',expected_updated=post['updated']))
        assert client.delete('/api/admin/blog/images/'+image['id'],headers=headers).status_code==200
        assert client.get(image['url']).status_code==404
        actions={e['action'] for e in client.get('/api/admin/audit').json()['items']}
        assert {'blog_image_added','blog_image_deleted'}<=actions
