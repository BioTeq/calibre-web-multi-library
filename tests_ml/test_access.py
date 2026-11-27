"""Phase 4: OPDS library list, per-user library access, Kobo library, admin Libraries page, serving guards."""
import io, os, re, sqlite3, zipfile
import requests
from conftest import BASE, make_test_bed, login

A, B = 'library-a', 'library-b'
AUTH = ('admin', 'admin123')


def token_of(s, base, url):
    return re.search(r'name="csrf_token" value="([^"]+)"', s.get(base + url).text).group(1)


# --- OPDS ----------------------------------------------------------------------------------------------------------

def test_opds_root_lists_the_libraries(server):
    r = requests.get(BASE + '/opds', auth=AUTH)
    assert r.ok and 'Library A' in r.text and 'Library B' in r.text
    assert f'/opds?library={B}' in r.text


def test_opds_library_root_has_wellformed_search(server):
    r = requests.get(BASE + '/opds', params={'library': B}, auth=AUTH)
    assert r.ok and 'Alphabetical Books' in r.text
    assert f'/opds/search/{{searchTerms}}?library={B}' in r.text, re.findall(r'href="[^"]*search[^"]*"', r.text)
    osd = requests.get(BASE + '/opds/osd', params={'library': B}, auth=AUTH).text
    assert f'/opds/search/{{searchTerms}}?library={B}' in osd
    assert f'/opds/search?query={{searchTerms}}&amp;library={B}' in osd
    hits = requests.get(BASE + '/opds/search/Bravo', params={'library': B}, auth=AUTH)
    assert hits.ok and 'Bravo One' in hits.text and 'Alpha One' not in hits.text


# --- per-user access -----------------------------------------------------------------------------------------------

def create_user(admin, base, name, ticked, default_library=0):
    data = {'csrf_token': token_of(admin, base, '/admin/user/new'), 'name': name, 'email': f'{name}@example.org',
            'password': 'Secret-pass-123', 'default_language': 'all', 'locale': 'en', 'show_32': 'on',
            'download_role': 'on', 'library_access_form': '1', 'default_library': str(default_library)}
    for lib_id in ticked:
        data[f'library_{lib_id}'] = 'on'
    r = admin.post(base + '/admin/user/new', data=data)
    assert r.ok


def test_user_limited_to_one_library(server):
    admin = login()
    form = admin.get(BASE + '/admin/user/new').text
    assert 'name="library_1"' in form and 'name="library_2"' in form, 'library fields missing on the user form'
    create_user(admin, BASE, 'onlyb', ticked=[2])
    s = login('onlyb', 'Secret-pass-123')
    assert 'Bravo One' in s.get(f'{BASE}/book/1').text                       # default: the only allowed library
    assert 'Bravo One' in s.get(f'{BASE}/book/1', params={'library': A}).text  # library A refused, stays in B
    assert 'library-switcher' not in s.get(BASE + '/').text                    # one library: no switcher
    feed = requests.get(BASE + '/opds/new', params={'library': A}, auth=('onlyb', 'Secret-pass-123')).text
    assert 'Bravo' in feed and 'Alpha' not in feed, 'OPDS showed a library the user may not open'


def test_user_default_library(server):
    admin = login()
    create_user(admin, BASE, 'defaultb', ticked=[1, 2], default_library=2)
    s = login('defaultb', 'Secret-pass-123')
    assert 'Bravo One' in s.get(f'{BASE}/book/1').text
    assert 'Alpha One' in s.get(f'{BASE}/book/1', params={'library': A}).text   # still allowed to switch


# --- Kobo ----------------------------------------------------------------------------------------------------------

def kobo_setup(app_db):
    c = sqlite3.connect(app_db)
    c.execute('update settings set config_kobo_sync=1')
    c.commit(); c.close()


def test_kobo_uses_the_users_kobo_library():
    with make_test_bed(port=8096, prepare=kobo_setup) as bed:
        c = sqlite3.connect(bed['app_db'])
        uid = c.execute("select id from user where name='admin'").fetchone()[0]
        c.execute('update user set kobo_library=2 where id=?', (uid,))
        c.execute("insert into remote_auth_token(auth_token, user_id, verified, expiration, token_type) "
                  "values ('kobotoken', ?, 1, '2999-01-01 00:00:00', 1)", (uid,))
        c.commit(); c.close()
        r = requests.get(bed['base'] + '/kobo/kobotoken/download/1/epub')
        assert r.ok, r.status_code
        opf = zipfile.ZipFile(io.BytesIO(r.content)).read('c.opf').decode()
        assert 'Bravo One' in opf, 'Kobo got the book from the wrong library'


# --- admin page and guards -----------------------------------------------------------------------------------------

def add_custom_column_to_b(app_db):
    db = os.path.join(os.path.dirname(app_db), 'libs', 'Library B', 'metadata.db')
    c = sqlite3.connect(db)
    c.execute("insert into custom_columns(label, name, datatype, mark_for_delete, editable, display, is_multiple, "
              "normalized) values ('mood', 'Mood', 'text', 0, 1, '{}', 0, 1)")
    c.commit(); c.close()


def test_library_with_different_custom_columns_is_not_served():
    with make_test_bed(port=8095, prepare=add_custom_column_to_b) as bed:
        s = login(base=bed['base'])
        assert 'Alpha One' in s.get(bed['base'] + '/book/1', params={'library': B}).text   # B refused -> A
        page = s.get(bed['base'] + '/admin/libraries').text
        assert 'Library B' in page and 'not served' in page


def test_admin_libraries_page_rename_disable_add():
    with make_test_bed(port=8094) as bed:
        base = bed['base']
        s = login(base=base)
        page = s.get(base + '/admin/libraries').text
        assert 'Library A' in page and 'Library B' in page
        # rename B and disable it
        data = {'csrf_token': token_of(s, base, '/admin/libraries'), 'action': 'save',
                'name_1': 'Library A', 'sort_1': '0', 'enabled_1': 'on', 'name_2': 'Second', 'sort_2': '1'}
        assert s.post(base + '/admin/libraries', data=data).ok
        assert 'Alpha One' in s.get(base + '/book/1', params={'library': B}).text      # B disabled
        assert 'library-switcher' not in s.get(base + '/').text
        # enable again
        data['enabled_2'] = 'on'; data['csrf_token'] = token_of(s, base, '/admin/libraries')
        assert s.post(base + '/admin/libraries', data=data).ok
        assert 'Second' in s.get(base + '/').text
        assert 'Bravo One' in s.get(base + '/book/1', params={'library': B}).text
        # add a third library by path
        import sample_libs
        sample_libs.build(os.path.join(bed['work'], 'elsewhere'), 'Library C', ['Charlie One'])
        data = {'csrf_token': token_of(s, base, '/admin/libraries'), 'action': 'add',
                'path': os.path.join(bed['work'], 'elsewhere', 'Library C')}
        assert s.post(base + '/admin/libraries', data=data).ok
        assert 'Charlie One' in s.get(base + '/book/1', params={'library': 'library-c'}).text
        # disabling every library is refused
        data = {'csrf_token': token_of(s, base, '/admin/libraries'), 'action': 'save'}
        s.post(base + '/admin/libraries', data=data)
        assert 'Alpha One' in s.get(base + '/book/1', params={'library': A}).text
