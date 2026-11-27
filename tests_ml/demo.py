"""Try multi-library Calibre-Web on generated sample libraries (nothing of yours is touched).

  python tests_ml/demo.py [folder] [port]

Builds three small libraries and a fresh app.db in `folder` (default: ./cw-demo, reused if it exists), then runs
Calibre-Web on http://127.0.0.1:<port> (default 8090). Log in as admin / admin123.
"""
import os, sqlite3, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sample_libs  # noqa: E402

LIBRARIES = {
    'Fiction': ['The Quiet Harbour', 'Northern Lights', 'A Long Winter', 'The Glass Garden', 'Paper Boats'],
    'Non-fiction': ['A Short History of Maps', 'Cooking With Salt', 'The Patient Gardener'],
    'Comics': ['Captain Teapot', 'Moonlight Detectives'],
}

FRESH_APP_DB = """
import sys
db = sys.argv[1]; sys.argv = ['cps.py', '-p', db]
from cps import ub, config_sql
ub.init_db(db)
config_sql.load_configuration(ub.session, None)
"""


def main():
    folder = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'cw-demo'))
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8090
    libs = os.path.join(folder, 'libs')
    app_db = os.path.join(folder, 'app.db')
    if not os.path.exists(app_db):
        for name, titles in LIBRARIES.items():
            sample_libs.build(libs, name, titles)
        subprocess.run([sys.executable, '-c', FRESH_APP_DB, app_db], cwd=ROOT, check=True)
        c = sqlite3.connect(app_db)
        c.execute('update settings set config_port=?, config_calibre_dir=?', (port, os.path.join(libs, 'Fiction')))
        c.commit(); c.close()
    env = dict(os.environ, CALIBRE_LIBRARY_ROOT=libs)
    os.chdir(ROOT)
    os.execve(sys.executable, [sys.executable, 'cps.py', '-p', app_db, '-o', os.path.join(folder, 'cw.log'),
                               '-i', '127.0.0.1'], env)


if __name__ == '__main__':
    main()
