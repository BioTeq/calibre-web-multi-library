"""Environment settings used by the Docker image: library root without a configured library, default library, port."""
import sqlite3
from conftest import make_test_bed, login


def fresh_install(app_db):
    c = sqlite3.connect(app_db)
    c.execute("update settings set config_calibre_dir=NULL, config_port=9")   # only the environment can make it work
    c.commit(); c.close()


def test_fresh_install_picks_default_library_and_port_from_environment():
    env = {'CALIBRE_WEB_PORT': '8092', 'CALIBRE_DEFAULT_LIBRARY': 'Library B'}
    with make_test_bed(port=8092, prepare=fresh_install, env_extra=env) as bed:
        s = login(base=bed['base'])
        assert 'Bravo One' in s.get(bed['base'] + '/book/1').text            # default library: B
        assert 'Alpha One' in s.get(bed['base'] + '/book/1', params={'library': 'library-a'}).text
        assert 'Check for Update' not in s.get(bed['base'] + '/admin/view').text   # no self-updater in the fork
