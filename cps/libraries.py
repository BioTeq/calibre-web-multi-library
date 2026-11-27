# -*- coding: utf-8 -*-

#  This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
#  Multi-library support: the registry of Calibre libraries and "the library of this request".
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Several Calibre libraries in one Calibre-Web.

* The registry lives in the app.db table ``library`` (model ``ub.Library``). On start it is filled from the classic
  setting ``config_calibre_dir`` (that library becomes the default, id 1) and, if the environment variable
  ``CALIBRE_LIBRARY_ROOT`` is set, from every sub-folder of that root which contains a ``metadata.db``.
* Each request works on exactly one library: ``?library=<slug>`` in the URL, else the one remembered in the
  session, else the default. ``current()`` returns it; outside a request (background tasks) ``use(lib)`` sets it
  for the running thread.
* With more than one library every ``url_for`` gets ``library=<slug>`` added, so links name their library.
"""

import os
import re
import threading
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass

from flask import g, has_app_context, has_request_context, request, session as flask_session

from . import logger

log = logger.create()

ENV_ROOT = 'CALIBRE_LIBRARY_ROOT'


@dataclass(frozen=True)
class Lib:
    id: int
    name: str
    slug: str
    path: str
    split_dir: str = None
    calibre_uuid: str = None

    @property
    def metadata_db(self):
        return os.path.join(self.path, 'metadata.db')

    @property
    def book_path(self):
        """Folder that holds the book folders (differs from path only for a calibre 'split library')."""
        return self.split_dir or self.path


_libs = []
_lock = threading.Lock()
_tls = threading.local()
_last_request_library = None


def slugify(name):
    s = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-') or 'library'


def _snapshot(row):
    return Lib(row.id, row.name, row.slug, row.path, row.split_dir or None, row.calibre_uuid)


def _read_only(path):
    import sqlite3, urllib.parse
    return sqlite3.connect('file:' + urllib.parse.quote(os.path.join(path, 'metadata.db')) + '?mode=ro', uri=True)


def custom_columns_signature(path):
    """The custom columns of a library: Calibre-Web maps them once for all libraries, so they must match."""
    try:
        con = _read_only(path)
        try:
            return tuple(con.execute('select id, label, datatype from custom_columns where mark_for_delete = 0 '
                                     'order by id').fetchall())
        finally:
            con.close()
    except Exception:
        return None


def book_count(path):
    try:
        con = _read_only(path)
        try:
            return con.execute('select count(*) from books').fetchone()[0]
        finally:
            con.close()
    except Exception:
        return None


def problem(row, first_signature):
    """Why a library can't be served (or None)."""
    if not os.path.isfile(os.path.join(row.path, 'metadata.db')):
        return 'metadata.db not found'
    if first_signature is not None and custom_columns_signature(row.path) != first_signature:
        return 'its custom columns differ from the default library'
    return None


def reload():
    """Re-read the registry from app.db: enabled libraries, in display order, that can be served together."""
    from . import ub, config
    rows = ub.session.query(ub.Library).filter(ub.Library.enabled == True).order_by(ub.Library.sort, ub.Library.id).all()
    rows = [r for r in rows if os.path.isfile(os.path.join(r.path, 'metadata.db'))]
    libs = []
    first_signature = custom_columns_signature(rows[0].path) if rows else None
    for r in rows:
        why = problem(r, first_signature)
        if why:
            log.warning('Library %s is not served: %s', r.name, why)
            continue
        libs.append(_snapshot(r))
    if len(libs) > 1 and getattr(config, 'config_use_google_drive', False):
        log.warning('Google Drive works with one library only; serving %s only', libs[0].name)
        libs = libs[:1]
    with _lock:
        _libs[:] = libs
    return list(_libs)


def all_libraries():
    return list(_libs)


def multiple():
    return len(_libs) > 1


def by_slug(slug):
    return next((lib for lib in _libs if lib.slug == slug), None) if slug else None


def by_id(lib_id):
    return next((lib for lib in _libs if lib.id == lib_id), None)


def default():
    return _libs[0] if _libs else None


def current():
    """The library this request (or this background thread) works on; the default one if nothing was chosen."""
    lib = getattr(_tls, 'library', None)
    if lib is not None:
        return lib
    if has_app_context():
        lib = g.get('library')
        if lib is not None:
            return lib
    return default()


@contextmanager
def use(lib):
    """Run a block (e.g. a background task) on a given library."""
    old = getattr(_tls, 'library', None)
    _tls.library = lib
    try:
        yield lib
    finally:
        _tls.library = old


def visible_to(user):
    """Libraries a user may open: admins all, others the ones in their allowed list ('' = all)."""
    libs = all_libraries()
    if user is None:
        return libs
    try:
        if user.role_admin():
            return libs
    except (AttributeError, TypeError):
        pass
    allowed = user.library_ids_allowed() if hasattr(user, 'library_ids_allowed') else None
    if allowed is None:
        return libs
    return [lib for lib in libs if lib.id in allowed]


def _request_user():
    try:
        from .cw_login import current_user
        return current_user._get_current_object() if current_user else None
    except Exception:
        return None


def select_for_request(user=None, prefer=None):
    """Decide the library of this request: ?library=, then the session's library, then `prefer`, then the user's
    default, then the first library the user may open. Called first in every request (user from the session) and
    again once a request has authenticated its user another way (OPDS basic auth, Kobo token)."""
    if not has_request_context():
        return None
    if user is None:
        user = _request_user()
    visible = visible_to(user)
    endpoint = request.endpoint or ''
    if (not visible and getattr(user, 'is_authenticated', False) and all_libraries()
            and 'static' not in endpoint and endpoint not in ('web.logout', 'web.login')):
        from flask import abort
        abort(403)            # the user may not open any library
    visible_slugs = {lib.slug: lib for lib in visible}
    wanted = request.args.get('library')
    lib = visible_slugs.get(wanted) or visible_slugs.get(flask_session.get('library'))
    if lib is None and prefer:
        lib = next((l for l in visible if l.id == prefer), None)
    if lib is None:
        dflt = getattr(user, 'default_library', 0) or 0
        lib = next((l for l in visible if l.id == dflt), None) or (visible[0] if visible else default())
    old = g.get('library')
    g.library = lib
    g.libraries = visible
    if old is not None and lib is not None and old.id != lib.id and g.get('lib_sql') is not None:
        try:
            g.lib_sql.close()
        finally:
            g.lib_sql = None          # the Calibre connection of the previous choice is closed, the next use reopens
    global _last_request_library
    if lib is not None and lib.id != _last_request_library:
        from . import ub
        ub.forget_state_objects()
        _last_request_library = lib.id
    if wanted and lib is not None and lib.slug == wanted and flask_session.get('library') != lib.slug:
        flask_session['library'] = lib.slug
    return lib


def add_library_to_url(endpoint, values):
    """app.url_defaults hook: every generated URL names its library (only when several libraries exist)."""
    if not multiple() or not endpoint or 'static' in endpoint or 'library' in values:
        return
    lib = g.get('library') if has_app_context() else None
    if lib is not None:
        values['library'] = lib.slug


def _unique_slug(session, name, own_id=None):
    from . import ub
    base = slugify(name); slug = base; n = 2
    while session.query(ub.Library).filter(ub.Library.slug == slug, ub.Library.id != (own_id or -1)).first():
        slug = f'{base}-{n}'; n += 1
    return slug


def sync_from_config(config):
    """Keep the registry in step with the classic single-library settings and the optional library root."""
    from . import ub
    s = ub.session
    lib_dir = config.config_calibre_dir
    if lib_dir and os.path.isfile(os.path.join(lib_dir, 'metadata.db')):
        first = s.query(ub.Library).order_by(ub.Library.id).first()
        split = config.config_calibre_split_dir if config.config_calibre_split else None
        if first is None:
            name = os.path.basename(os.path.normpath(lib_dir))
            s.add(ub.Library(name=name, slug=_unique_slug(s, name), path=lib_dir, split_dir=split, sort=0))
        elif first.path != lib_dir or first.split_dir != split:
            # the classic "database configuration" page edits the default library
            first.path, first.split_dir = lib_dir, split
    root = os.environ.get(ENV_ROOT)
    if root and os.path.isdir(root):
        known = {os.path.realpath(r.path) for r in s.query(ub.Library).all()}
        top = (s.query(ub.func.max(ub.Library.sort)).scalar() or 0) if hasattr(ub, 'func') else 0
        for entry in sorted(os.listdir(root)):
            p = os.path.join(root, entry)
            if entry.startswith(('.', '_')) or not os.path.isfile(os.path.join(p, 'metadata.db')):
                continue
            if os.path.realpath(p) in known:
                continue
            top += 1
            s.add(ub.Library(name=entry, slug=_unique_slug(s, entry), path=p, sort=top))
            log.info('Library found under %s: %s', root, entry)
    try:
        s.commit()
    except Exception as e:
        s.rollback()
        log.error('Could not update the library registry: %s', e)
    libs = reload()
    log.info('Libraries: %s', ', '.join(f'{l.name} ({l.slug})' for l in libs) or 'none')
    return libs
