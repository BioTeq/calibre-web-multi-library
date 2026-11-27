"""Phase 2: upgrading a single-library install. Its book state (read status, shelves) sits in app.db and must move
into the default library's state database, without leaking into other libraries."""
import os, re, sqlite3, subprocess, sys
from conftest import ROOT, make_test_bed, login

PORT = 8098

OLD_STYLE_STATE = """
import sys
db = sys.argv[1]; sys.argv = ['cps.py', '-p', db]
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from cps import ub
engine = create_engine('sqlite:///' + db)
ub.Base.metadata.create_all(engine, tables=ub.state_tables())     # tables as a single-library app.db has them
s = Session(bind=engine)
admin = s.query(ub.User).filter(ub.User.name == 'admin').one()
s.add(ub.ReadBook(user_id=admin.id, book_id=2, read_status=ub.ReadBook.STATUS_FINISHED))
shelf = ub.Shelf(name='Old shelf', is_public=0, user_id=admin.id)
s.add(shelf); s.flush()
link = ub.BookShelf(book_id=1, order=1); link.ub_shelf = shelf; s.add(link)
s.commit()
"""


def old_install(app_db):
    subprocess.run([sys.executable, '-c', OLD_STYLE_STATE, app_db], cwd=ROOT, check=True, capture_output=True)


def test_state_moves_to_default_library():
    with make_test_bed(port=PORT, prepare=old_install) as bed:
        base = bed['base']; s = login(base=base)
        cfg = os.path.dirname(bed['app_db'])
        assert os.path.exists(bed['app_db'] + '.before-multi-library'), 'no backup of app.db'
        tables = {r[0] for r in sqlite3.connect(bed['app_db']).execute("select name from sqlite_master where type='table'")}
        assert not tables & {'book_read_link', 'shelf', 'book_shelf_link'}, tables
        st = sqlite3.connect(os.path.join(cfg, 'libraries', 'library-1.db'))
        assert st.execute('select count(*) from book_read_link where book_id=2').fetchone()[0] == 1
        assert st.execute("select count(*) from shelf where name='Old shelf'").fetchone()[0] == 1

        def read(lib):
            page = s.get(f'{base}/book/2', params={'library': lib}).text.replace('\n', ' ')
            return bool(re.search(r'id="have_read_cb"[^>]*checked', page))
        assert read('library-a'), 'old read status lost'
        assert not read('library-b'), 'old read status leaked into the new library'
        assert 'Old shelf' in s.get(base + '/', params={'library': 'library-a'}).text
        assert 'Old shelf' not in s.get(base + '/', params={'library': 'library-b'}).text


def strip_multi_library_columns(app_db):
    c = sqlite3.connect(app_db)
    for col in ('allowed_libraries', 'default_library', 'kobo_library'):
        c.execute(f'alter table user drop column {col}')
    c.execute('drop table library')
    c.commit(); c.close()


def test_user_table_of_an_older_install_is_upgraded():
    with make_test_bed(port=8093, prepare=strip_multi_library_columns) as bed:
        cols = {r[1] for r in sqlite3.connect(bed['app_db']).execute('pragma table_info(user)')}
        assert {'allowed_libraries', 'default_library', 'kobo_library'} <= cols
        s = login(base=bed['base'])
        assert 'Bravo One' in s.get(bed['base'] + '/book/1', params={'library': 'library-b'}).text
