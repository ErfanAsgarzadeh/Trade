"""Server-rendered public pages in the blog's shell: trust pages, product pages and the methodology. Rendering on the server
keeps the copy (and the admin-edited contact details) visible to crawlers without JavaScript."""
import html
import json
from pathlib import Path

import portal_blog
from portal_blog import _e, _ld, _page, path as lang_path
from portal_pages_content import CONTENT, NAMES, ORDER

SLUGS = ORDER
SERVER_PAGES = tuple(p for slug in SLUGS for p in (f'/{slug}/', f'/en/{slug}/'))
PUBLIC_DIR = Path(__file__).with_name('frontend') / 'public' / 'backtest'
CTA = {'fa': ('ساخت حساب و شروع', 'ورود به پنل', 'اگر آماده‌اید، حساب بسازید؛ سرمایه در حساب صرافی خودتان می‌ماند و هیچ سودی تضمین نمی‌شود.'),
       'en': ('Create an account', 'Sign in', 'When you are ready, create an account. Your funds stay in your own exchange account and no profit is guaranteed.')}
LABELS = {'fa': dict(home='آوینا', terms_note='', contact_none='هنوز راه تماس عمومی ثبت نشده است. لطفاً از ربات تلگرام یا از داخل پنل خود با ما در ارتباط باشید.',
                     email='ایمیل پشتیبانی', telegram='تلگرام', other='راه دیگر', capital='سقف سرمایه', month='ماه', closed='فروش فعلاً بسته است؛ قیمت‌ها با باز شدن فروش اینجا نمایش داده می‌شوند.',
                     exchange='صرافی', markets='بازارها', needs='فیلدهای لازم', pending='در انتظار فعال‌سازی', spot='اسپات', futures='فیوچرز',
                     faq='پرسش‌های پرتکرار', more='ادامه بدهید', product_signals='فقط سیگنال', product_autotrade='معاملهٔ خودکار', prices_note='قیمت‌ها به دلار آمریکا و برای هر دوره است.',
                     updated='آخرین به‌روزرسانی', keyfield={'apiKey': 'کلید API', 'secret': 'رمز API', 'password': 'عبارت عبور', 'uid': 'شناسه کاربر'}),
          'en': dict(home='Avina', terms_note='', contact_none='No public contact details have been published yet. Please contact us through the Telegram bot or from inside your panel.',
                     email='Support e-mail', telegram='Telegram', other='Other', capital='Capital cap', month='mo', closed='Sales are closed for now; prices appear here when sales open.',
                     exchange='Exchange', markets='Markets', needs='Required fields', pending='Pending activation', spot='Spot', futures='Futures',
                     faq='Frequently asked questions', more='Keep reading', product_signals='Signals only', product_autotrade='Automated trading', prices_note='Prices are in US dollars per term.',
                     updated='Last updated', keyfield={'apiKey': 'API key', 'secret': 'API secret', 'password': 'Passphrase', 'uid': 'User ID'})}
MONTH_NAMES = {'fa': {1: '۱ ماهه', 3: '۳ ماهه', 6: '۶ ماهه'}, 'en': {1: '1 month', 3: '3 months', 6: '6 months'}}
FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def page_path(slug, lang):
    return lang_path(lang, f'/{slug}/')


def slug_of(path):
    """The page slug for a canonical path, or None."""
    for slug in SLUGS:
        if path in (f'/{slug}/', f'/en/{slug}/'):return slug
    return None


def _paragraph(item):
    if isinstance(item, list):
        return '<ul>' + ''.join(f'<li>{_e(i)}</li>' for i in item) + '</ul>'
    return f'<p>{_e(item)}</p>'


def _money(cents, lang):
    value = f'${cents / 100:,.2f}'.replace('.00', '')
    return value.translate(FA_DIGITS) if lang == 'fa' else value


def lowest_prices(plans):
    """{product: lowest price in cents} for products whose sales are open and have prices set."""
    out = {}
    for product in (plans or {}).get('products', []):
        if not product.get('sales_enabled'):continue
        prices = [c for tier in product['tiers'] for c in tier['prices_cents'].values() if c]
        if prices:out[product['product']] = min(prices)
    return out


def _pricing_tables(plans, lang):
    t = LABELS[lang]
    if not lowest_prices(plans):return f'<p>{t["closed"]}</p>'
    out = f'<p>{t["prices_note"]}</p>'
    for product in plans['products']:
        if not product.get('sales_enabled'):continue
        terms = sorted({int(k) for tier in product['tiers'] for k in tier['prices_cents']})
        name = t['product_' + product['product']] if 'product_' + product['product'] in t else product['label']
        head = ''.join(f'<th scope="col">{MONTH_NAMES[lang].get(m, str(m))}</th>' for m in terms)
        rows = ''
        for tier in product['tiers']:
            cap = f'${tier["cap_usd"]:,}'.translate(FA_DIGITS) if lang == 'fa' else f'${tier["cap_usd"]:,}'
            cells = ''.join('<td>' + (_money(tier['prices_cents'][str(m)], lang) if tier['prices_cents'].get(str(m)) else '-') + '</td>' for m in terms)
            rows += f'<tr><th scope="row">{cap}</th>{cells}</tr>'
        out += (f'<h3>{_e(name)}</h3><div class="forward-table-scroll" tabindex="0"><table><caption class="sr-only">{_e(name)}</caption>'
                f'<thead><tr><th scope="col">{t["capital"]}</th>{head}</tr></thead><tbody>{rows}</tbody></table></div>')
    return out


def _exchange_table(exchanges, lang):
    t = LABELS[lang]
    rows = ''
    for item in exchanges:
        markets = ', '.join(t[m] for m in item['markets']) or '-'
        if item.get('pending_markets'):
            markets += ' (' + ', '.join(t[m] + ': ' + t['pending'] for m in item['pending_markets']) + ')'
        fields = sorted({f for fl in item['required_fields'].values() for f in fl})
        rows += f'<tr><th scope="row">{_e(item["name"])}</th><td>{_e(markets)}</td><td>{_e(", ".join(t["keyfield"].get(f, f) for f in fields))}</td></tr>'
    return (f'<div class="forward-table-scroll" tabindex="0"><table><caption class="sr-only">{t["exchange"]}</caption><thead><tr>'
            f'<th scope="col">{t["exchange"]}</th><th scope="col">{t["markets"]}</th><th scope="col">{t["needs"]}</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


def _contact(info, lang):
    t = LABELS[lang]
    items = []
    if info.get('support_email'):
        mail = _e(info['support_email'])
        items.append(f'<li>{t["email"]}: <a href="mailto:{mail}">{mail}</a></li>')
    if info.get('telegram_id') or info.get('telegram_link'):
        label = _e(info.get('telegram_id') or info['telegram_link'])
        link = f'<a href="{_e(info["telegram_link"])}" rel="noopener">{label}</a>' if info.get('telegram_link') else f'<bdi>{label}</bdi>'
        items.append(f'<li>{t["telegram"]}: {link}</li>')
    if info.get('other_line'):
        items.append(f'<li>{t["other"]}: {_e(info["other_line"])}</li>')
    return '<ul>' + ''.join(items) + '</ul>' if items else f'<p>{t["contact_none"]}</p>'


def _methodology(lang):
    try:
        text = (PUBLIC_DIR / f'methodology-{lang}.md').read_text(encoding='utf-8')
    except OSError:
        return ''
    lines = text.splitlines()
    if lines and lines[0].startswith('# '):lines = lines[1:]
    return portal_blog.render_body('\n'.join(lines))


def build(slug, lang, origin, css, plans=None, exchanges=None, info=None, updated=None):
    """The complete HTML of one page."""
    data = CONTENT[slug][lang]
    t = LABELS[lang]
    canonical = page_path(slug, lang)
    url = origin + canonical
    parts = []
    for heading, items in data['sections']:
        parts.append(f'<h2>{_e(heading)}</h2>' + ''.join(_paragraph(i) for i in items))
        if slug == 'pricing' and heading == data['sections'][0][0]:
            parts.append(f'<h2>{_e(t["product_signals"])} / {_e(t["product_autotrade"])}</h2>' + _pricing_tables(plans, lang))
        if slug == 'exchanges' and heading == data['sections'][0][0]:
            parts.append(_exchange_table(exchanges or [], lang))
    if slug == 'contact':
        parts.insert(0, _contact(info or {}, lang))
    if slug == 'methodology':
        parts = [_methodology(lang)]
    faq = data.get('faq')
    if faq:
        parts.append(f'<h2>{t["faq"]}</h2>' + ''.join(f'<h3>{_e(q)}</h3><p>{_e(a)}</p>' for q, a in faq))
    links = data.get('links') or []
    nav = ''
    if links:
        nav = (f'<nav class="page-links" aria-label="{t["more"]}"><ul>' + ''.join(
            f'<li><a href="{lang_path(lang, "/" + target + "/")}">{_e(label)}</a></li>' for target, label in links) + '</ul></nav>')
    cta_button, cta_signin, cta_text = CTA[lang]
    cta = (f'<aside class="blog-cta" aria-label="{_e(cta_button)}"><h2>{_e(cta_button)}</h2><p>{_e(cta_text)}</p><div>'
           f'<a class="landing-primary" href="{lang_path(lang, "/register/")}">{_e(cta_button)}</a>'
           f'<a class="landing-secondary" href="{lang_path(lang, "/dashboard/")}">{_e(cta_signin)}</a></div></aside>')
    lead = f'<p class="blog-lead">{_e(data["lead"])}</p>' if data['lead'] else ''
    body = (f'<article class="blog-article"><nav class="blog-breadcrumb" aria-label="{portal_blog.TEXT[lang]["crumbs"]}">'
            f'<a href="{lang_path(lang, "/")}">{portal_blog.TEXT[lang]["brand"]}</a><span aria-hidden="true">/</span>'
            f'<span>{_e(NAMES[slug][0 if lang == "fa" else 1])}</span></nav>'
            f'<header class="blog-article-head"><h1>{_e(data["h1"])}</h1>{lead}</header>'
            f'<div class="blog-body">{"".join(parts)}</div>{nav}</article>{cta if slug not in ("terms", "privacy", "risk") else ""}')
    crumbs = {'@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': 1, 'name': portal_blog.TEXT[lang]['brand'], 'item': origin + lang_path(lang, '/')},
        {'@type': 'ListItem', 'position': 2, 'name': data['h1'], 'item': url}]}
    graph = [crumbs]
    if faq:
        graph.append({'@type': 'FAQPage', 'inLanguage': lang, 'mainEntity': [
            {'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in faq]})
    if slug == 'pricing':
        offers = _offers(plans, lang, origin)
        if offers:
            graph.append({'@type': 'SoftwareApplication', 'name': 'Avina', 'url': origin + lang_path(lang, '/'), 'applicationCategory': 'FinanceApplication',
                          'operatingSystem': 'Web', 'inLanguage': lang, 'offers': offers})
    if slug == 'contact' and info and any(info.get(k) for k in ('support_email', 'telegram_link')):
        point = {'@type': 'ContactPoint', 'contactType': 'customer support', 'availableLanguage': ['fa', 'en']}
        if info.get('support_email'):point['email'] = info['support_email']
        if info.get('telegram_link'):point['url'] = info['telegram_link']
        graph.append({'@type': 'Organization', '@id': origin + '/#org', 'name': 'Avina', 'url': origin + '/', 'contactPoint': point})
    head = _ld({'@context': 'https://schema.org', '@graph': graph})
    alternates = {code: page_path(slug, code) for code in portal_blog.LANGS}
    other = 'en' if lang == 'fa' else 'fa'
    return _page(origin, css, lang, canonical, data['title'], data['description'], 'website', head, body, alternates, page_path(slug, other))


def _offers(plans, lang, origin):
    out = []
    for product in (plans or {}).get('products', []):
        low = lowest_prices({'products': [product]}).get(product['product'])
        if low:
            out.append({'@type': 'Offer', 'name': 'Avina ' + product['product'], 'price': f'{low / 100:.2f}', 'priceCurrency': 'USD',
                        'availability': 'https://schema.org/InStock', 'url': origin + lang_path(lang, '/register/')})
    return out
