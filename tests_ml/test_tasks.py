"""Phase 3: background work per library, and user deletion across libraries."""
import os, re, sqlite3, time
import requests
from conftest import BASE, make_test_bed, login

PORT = 8097


def dirty_book_1_and_schedule_backup(app_db):
    libs = os.path.join(os.path.dirname(app_db), 'libs')
    for name in ('Library A', 'Library B'):
        c = sqlite3.connect(os.path.join(libs, name, 'metadata.db'))
        c.execute('insert into metadata_dirtied(book) values (1)')
        c.commit(); c.close()
    c = sqlite3.connect(app_db)
    c.execute('update settings set schedule_metadata_backup=1')
    c.commit(); c.close()


def test_scheduled_backup_runs_for_every_library():
    # APP_MODE=test runs the scheduled jobs right after the start
    with make_test_bed(port=PORT, prepare=dirty_book_1_and_schedule_backup, env_extra={'APP_MODE': 'test'}) as bed:
        expected = {'Library A': ('Alpha One', 'Sample Author/Alpha One (1)'),
                    'Library B': ('Bravo One', 'Sample Author/Bravo One (1)')}
        deadline = time.time() + 30
        found = {}
        while time.time() < deadline and len(found) < 2:
            for lib, (title, rel) in expected.items():
                opf = os.path.join(bed['libs'], lib, rel, 'metadata.opf')
                if os.path.exists(opf):
                    found[lib] = open(opf, encoding='utf-8').read()
            time.sleep(0.5)
        assert set(found) == set(expected), f'metadata.opf written only for {sorted(found)}'
        for lib, (title, _) in expected.items():
            assert f'<dc:title>{title}</dc:title>' in found[lib], lib


def test_deleting_a_user_clears_their_state_in_every_library(server):
    app_db = server['app_db']
    cfg = os.path.dirname(app_db)
    c = sqlite3.connect(app_db)
    c.execute("insert into user(name, email, role, password, kindle_mail, locale, sidebar_view, default_language, "
              "denied_tags, allowed_tags, denied_column_value, allowed_column_value, view_settings, kobo_only_shelves_sync) "
              "values ('reader', 'reader@example.org', 0, '', '', 'en', 1, 'all', '', '', '', '', '{}', 0)")
    c.commit()
    uid = c.execute("select id from user where name='reader'").fetchone()[0]
    c.close()
    admin = login()
    for lib in ('library-a', 'library-b'):           # make sure both state databases exist
        admin.get(BASE + '/', params={'library': lib})
    for n in (1, 2):
        st = sqlite3.connect(os.path.join(cfg, 'libraries', f'library-{n}.db'))
        st.execute('insert into book_read_link(book_id, user_id, read_status, times_started_reading) values (1, ?, 1, 0)', (uid,))
        st.execute("insert into shelf(uuid, name, is_public, user_id, kobo_sync) values (?, 'reader shelf', 0, ?, 0)",
                   (f'u{n}', uid))
        st.commit(); st.close()
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', admin.get(BASE + '/admin/view').text) or \
        re.search(r'name="csrf_token" value="([^"]+)"', admin.get(BASE + '/admin/view').text)
    r = admin.post(BASE + '/ajax/deleteuser', json={'userid': [uid]}, headers={'X-CSRFToken': token.group(1)})
    assert r.ok and 'deleted' in r.text.lower(), r.text[:300]
    for n in (1, 2):
        st = sqlite3.connect(os.path.join(cfg, 'libraries', f'library-{n}.db'))
        assert st.execute('select count(*) from book_read_link where user_id=?', (uid,)).fetchone()[0] == 0, n
        assert st.execute('select count(*) from shelf where user_id=?', (uid,)).fetchone()[0] == 0, n
    assert sqlite3.connect(app_db).execute('select count(*) from user where id=?', (uid,)).fetchone()[0] == 0
