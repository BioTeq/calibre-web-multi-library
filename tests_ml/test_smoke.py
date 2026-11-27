"""Phase 0 smoke tests: what a single-library calibre-web does today must keep working."""
import re
from conftest import BASE


def first_book_id(s, url='/'):
    m = re.search(r'href="/book/(\d+)', s.get(BASE + url).text)
    assert m, 'no book link on ' + url
    return int(m.group(1))


def test_index_lists_books(admin):
    r = admin.get(BASE + '/')
    assert r.ok and '/book/' in r.text


def test_book_page_cover_download(admin):
    i = first_book_id(admin)
    page = admin.get(f'{BASE}/book/{i}')
    assert page.ok
    assert admin.get(f'{BASE}/cover/{i}').headers['content-type'].startswith('image/')
    m = re.search(r'href="(/download/%d/[a-z0-9]+/[^"]*)"' % i, page.text)
    assert m, 'no download link'
    d = admin.get(BASE + m.group(1))
    assert d.ok and len(d.content) > 1000


def test_search(admin):
    assert admin.get(BASE + '/search', params={'query': 'a'}).ok


def test_opds_root(admin):
    r = admin.get(BASE + '/opds', auth=('admin', 'admin123'))
    assert r.ok and '<feed' in r.text


def test_opds_new(admin):
    r = admin.get(BASE + '/opds/new', auth=('admin', 'admin123'))
    assert r.ok and '<entry>' in r.text


def test_read_status_toggle(admin):
    i = first_book_id(admin)
    token = re.search(r'name="csrf_token" value="([^"]+)"', admin.get(f'{BASE}/book/{i}').text).group(1)
    r = admin.post(f'{BASE}/ajax/toggleread/{i}', headers={'X-CSRFToken': token})
    assert r.ok
