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
    assert seeded>=5 and len(blog.published())==seeded
    victim=blog.all()[0]
    with store.db() as db:actor=db.execute("SELECT id FROM users WHERE username='manager'").fetchone()['id']
    blog.delete(actor,victim['id'],victim['updated'])
    assert blog.seed()==0 and len(blog.all())==seeded-1


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
