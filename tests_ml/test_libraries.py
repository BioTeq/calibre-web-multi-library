"""Several libraries in one instance. Sample libraries A (default) and B both have books 1, 2, 3 (see conftest.py)."""
import hashlib, re
import requests
from conftest import BASE, login

A, B = 'library-a', 'library-b'
TITLE = {A: 'Alpha One', B: 'Bravo One'}          # book id 1 in each library


def test_book_1_is_different_per_library(admin):
    for slug, title in TITLE.items():
        r = admin.get(f'{BASE}/book/1', params={'library': slug})
        assert r.ok and title in r.text, slug


def test_index_follows_library(admin):
    assert 'Bravo Only Here' in admin.get(BASE + '/', params={'library': B}).text
    assert 'Bravo Only Here' not in admin.get(BASE + '/', params={'library': A}).text


def test_choice_is_remembered_in_session(server):
    s = login()
    s.get(BASE + '/', params={'library': B})
    assert TITLE[B] in s.get(f'{BASE}/book/1').text
    s.get(BASE + '/', params={'library': A})
    assert TITLE[A] in s.get(f'{BASE}/book/1').text


def test_links_carry_the_library(admin):
    page = admin.get(BASE + '/', params={'library': B}).text
    book_links = re.findall(r'href="(/book/\d+[^"]*)"', page)
    assert book_links and all(f'library={B}' in l for l in book_links), book_links[:3]
    covers = re.findall(r'src="(/cover/\d+[^"]*)"', page)
    assert covers and all(f'library={B}' in c for c in covers), covers[:3]


def test_cover_and_download_come_from_the_right_library(admin):
    a = admin.get(f'{BASE}/cover/1', params={'library': A}).content
    b = admin.get(f'{BASE}/cover/1', params={'library': B}).content
    assert hashlib.md5(a).digest() != hashlib.md5(b).digest()
    page = admin.get(f'{BASE}/book/1', params={'library': B}).text
    link = re.search(r'href="(/download/1/[a-z0-9]+/[^"]*)"', page).group(1).replace('&amp;', '&')
    assert f'library={B}' in link
    assert admin.get(BASE + link).ok


def test_unknown_library_falls_back_to_default(server):
    s = login()
    assert TITLE[A] in s.get(f'{BASE}/book/1', params={'library': 'nope'}).text


def test_opds_per_library(server):
    for slug, title in TITLE.items():
        r = requests.get(f'{BASE}/opds/new', params={'library': slug}, auth=('admin', 'admin123'))
        assert r.ok and title in r.text, slug
        assert f'library={slug}' in r.text   # links inside the feed keep the library


def test_switcher_lists_libraries(admin):
    page = admin.get(BASE + '/').text
    assert 'Library A' in page and 'Library B' in page
