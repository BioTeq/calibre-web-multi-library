"""Test bed for multi-library support: a real Calibre-Web server on two generated sample libraries.

Each test session builds, in a temporary folder:
  libs/Library A, libs/Library B   books 1-3 in each (ids clash on purpose), see sample_libs.py
  app.db                           fresh settings, default library = Library A, port 8099, user admin/admin123
and starts the server with CALIBRE_LIBRARY_ROOT=libs, so Library B is found on its own.
Run:  python -m pytest tests_ml -q      (CWTEST_KEEP=1 keeps the temporary folder for inspection)
"""
import contextlib, os, re, shutil, signal, sqlite3, subprocess, sys, tempfile, time
import pytest, requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sample_libs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get('CWTEST_PORT', 8099))
BASE = f'http://127.0.0.1:{PORT}'
LIBRARIES = {
    'Library A': ['Alpha One', 'Alpha Two', 'Alpha Three'],
    'Library B': ['Bravo One', 'Bravo Two', 'Bravo Only Here'],
}

FRESH_APP_DB = """
import sys
db = sys.argv[1]; sys.argv = ['cps.py', '-p', db]
from cps import ub, config_sql
ub.init_db(db)
config_sql.load_configuration(ub.session, None)
"""


def wait_up(proc, log, base=BASE):
    for _ in range(120):
        if proc.poll() is not None:
            raise RuntimeError('server exited:\n' + open(log).read()[-3000:])
        try:
            requests.get(base + '/login', timeout=1); return
        except requests.ConnectionError:
            time.sleep(0.5)
    raise RuntimeError('server did not start:\n' + open(log).read()[-3000:])


@contextlib.contextmanager
def make_test_bed(port=PORT, prepare=None):
    """Sample libraries + fresh app.db + running server. prepare(app_db) may change app.db before the start."""
    work = tempfile.mkdtemp(prefix='cwtest-')
    libs = os.path.join(work, 'libs')
    for name, titles in LIBRARIES.items():
        sample_libs.build(libs, name, titles)
    app_db = os.path.join(work, 'app.db')
    subprocess.run([sys.executable, '-c', FRESH_APP_DB, app_db], cwd=ROOT, check=True, capture_output=True)
    c = sqlite3.connect(app_db)
    c.execute('update settings set config_port=?, config_calibre_dir=?', (port, os.path.join(libs, 'Library A')))
    c.commit(); c.close()
    if prepare:
        prepare(app_db)
    log = os.path.join(work, 'stdout.log')
    env = dict(os.environ, CALIBRE_LIBRARY_ROOT=libs)
    proc = subprocess.Popen([sys.executable, 'cps.py', '-p', app_db, '-o', os.path.join(work, 'cw.log'), '-i', '127.0.0.1'],
                            cwd=ROOT, stdout=open(log, 'w'), stderr=subprocess.STDOUT, env=env, start_new_session=True)
    try:
        wait_up(proc, log, f'http://127.0.0.1:{port}')
        yield {'work': work, 'app_db': app_db, 'libs': libs, 'log': log, 'base': f'http://127.0.0.1:{port}'}
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        try: proc.wait(10)
        except subprocess.TimeoutExpired: os.killpg(proc.pid, signal.SIGKILL)
        if not os.environ.get('CWTEST_KEEP'): shutil.rmtree(work, ignore_errors=True)


@pytest.fixture(scope='session')
def server():
    with make_test_bed() as bed:
        yield bed


def login(user='admin', password='admin123', base=BASE):
    s = requests.Session()
    page = s.get(base + '/login').text
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    r = s.post(base + '/login', data={'username': user, 'password': password, 'csrf_token': token, 'next': '/'})
    assert r.ok and 'logout' in r.text.lower(), 'login failed'
    return s


@pytest.fixture(scope='session')
def admin(server):
    return login()
