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


def slugify(name):
    s = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-') or 'library'


def _snapshot(row):
    return Lib(row.id, row.name, row.slug, row.path, row.split_dir or None, row.calibre_uuid)


def reload():
    """Re-read the registry from app.db (enabled libraries, in display order)."""
    from . import ub
    rows = ub.session.query(ub.Library).filter(ub.Library.enabled == True).order_by(ub.Library.sort, ub.Library.id).all()
    with _lock:
        _libs[:] = [_snapshot(r) for r in rows if os.path.isfile(os.path.join(r.path, 'metadata.db'))]
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


def select_for_request():
    """Called first in every request: decide the library and remember an explicit choice in the session."""
    if not has_request_context():
        return None
    wanted = request.args.get('library')
    lib = by_slug(wanted)
    if lib is None:
        lib = by_slug(flask_session.get('library')) or default()
    g.library = lib
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
