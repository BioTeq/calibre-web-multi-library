"""Phase 2: per-user reading state is kept per library (sample libraries A and B both have books 1-3)."""
import os, re, sqlite3
from conftest import BASE, login

A, B = 'library-a', 'library-b'


def csrf(s, url, **params):
    return re.search(r'name="csrf_token" value="([^"]+)"', s.get(BASE + url, params=params).text).group(1)


def is_read(s, lib, book):
    page = s.get(f'{BASE}/book/{book}', params={'library': lib}).text
    return bool(re.search(r'id="have_read_cb"[^>]*checked', page.replace('\n', ' ')))


def is_archived(s, lib, book):
    page = s.get(f'{BASE}/book/{book}', params={'library': lib}).text
    return bool(re.search(r'id="archived_cb"[^>]*checked', page.replace('\n', ' ')))


def test_read_status_is_per_library(server):
    s = login()
    before_a, before_b = is_read(s, A, 2), is_read(s, B, 2)
    token = csrf(s, '/book/2', library=A)
    assert s.post(f'{BASE}/ajax/toggleread/2', params={'library': A}, headers={'X-CSRFToken': token}).ok
    assert is_read(s, A, 2) != before_a, 'toggle had no effect'
    assert is_read(s, B, 2) == before_b, 'read status leaked from library A to library B'


def test_archive_is_per_library(server):
    s = login()
    before_a, before_b = is_archived(s, A, 3), is_archived(s, B, 3)
    token = csrf(s, '/book/3', library=B)
    assert s.post(f'{BASE}/ajax/togglearchived/3', params={'library': B}, headers={'X-CSRFToken': token}).ok
    assert is_archived(s, B, 3) != before_b, 'toggle had no effect'
    assert is_archived(s, A, 3) == before_a, 'archive flag leaked from library B to library A'


def test_shelves_are_per_library(server):
    s = login()
    token = csrf(s, '/shelf/create', library=A)
    r = s.post(f'{BASE}/shelf/create', params={'library': A}, data={'title': 'Shelf in A', 'csrf_token': token})
    assert r.ok
    assert 'Shelf in A' in s.get(BASE + '/', params={'library': A}).text
    assert 'Shelf in A' not in s.get(BASE + '/', params={'library': B}).text, 'shelf leaked from A to B'
    shelf_id = int(re.search(r'href="/shelf/(\d+)[^"]*"[^>]*>\s*<span class="glyphicon glyphicon-list shelf"></span> Shelf in A',
                             s.get(BASE + '/', params={'library': A}).text).group(1))
    token = csrf(s, '/book/1', library=A)
    assert s.post(f'{BASE}/shelf/add/{shelf_id}/1', params={'library': A}, headers={'X-CSRFToken': token}).ok
    shelf_page = s.get(f'{BASE}/shelf/{shelf_id}', params={'library': A}).text
    assert 'Alpha One' in shelf_page and 'Bravo One' not in shelf_page


def test_state_lives_in_one_file_per_library(server):
    cfg = os.path.dirname(server['app_db'])
    files = sorted(os.listdir(os.path.join(cfg, 'libraries')))
    assert 'library-1.db' in files and 'library-2.db' in files, files
    app_tables = {r[0] for r in sqlite3.connect(server['app_db']).execute("select name from sqlite_master where type='table'")}
    assert 'book_read_link' not in app_tables and 'shelf' not in app_tables, 'book state still in app.db'
    s = login()
    for lib, n in ((A, 1), (B, 2)):        # what the UI shows is what the library's own state file says
        st = sqlite3.connect(os.path.join(cfg, 'libraries', f'library-{n}.db'))
        stored = st.execute('select count(*) from book_read_link where book_id=2 and read_status=1').fetchone()[0] == 1
        assert stored == is_read(s, lib, 2), lib
