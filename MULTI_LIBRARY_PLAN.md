# Multi-library support for Calibre-Web: design and plan

Goal: one Calibre-Web instance serves several Calibre libraries. Users switch between them in the web UI, OPDS
lists them all, and each user's reading state (read status, shelves, bookmarks, Kobo sync…) stays correct for each library.
Based on Calibre-Web `0.6.28b` with the theme system (`cps/themes/{standard,caliblur,simple}`).

## 1. How the code works today

| Area | Today | Problem with several libraries |
|---|---|---|
| Library location | One global setting `config.config_calibre_dir` (+ `config_calibre_split_dir`), read through `config.get_book_path()` and directly in a few runtime places (`embed_helper.py`, `helper.py`, `kobo_auth.py`, `web.py`, `tasks/convert.py`). | Must become "the library of this request". |
| Database connection | `CalibreDB.session` (`cps/db.py`) opens **a new engine per request**: an in-memory SQLite connection that `ATTACH`es `metadata.db` as `calibre` and `app.db` as `app_settings`, cached in `g.lib_sql`. | Since it's per request already, choosing a different `metadata.db` per request is cheap. Only the source of the path changes. |
| Custom columns | Global: `cc_classes` and `setattr(Books, 'custom_column_N', …)` are built once from the first library opened. | Libraries with different custom columns would clash. |
| Per-user book state in `app.db` | `shelf`, `book_shelf_link`, `shelf_archive`, `book_read_link`, `bookmark`, `archived_book`, `downloads`, `kobo_synced_books`, `kobo_reading_state` (+ `kobo_bookmark`, `kobo_statistics`), `thumbnail`: keyed by **book id only**. | Book 42 in library A and book 42 in library B would share read status, shelves, bookmarks, archive flag, Kobo state and thumbnails. A `library_id` column would mean filtering ~200 queries (kobo.py 44, shelf.py 30, web.py 27, tasks/thumbnail.py 19, helper.py 18, db.py 16, kobo_sync_status.py 15, admin.py 15, search.py 9, opds.py 8, editbooks.py 2). |
| Per-library settings | `config_calibre_uuid`, `config_read_column`, `config_restricted_column`, `config_columns_to_ignore`, `config_calibre_split(_dir)`, `config_use_google_drive`, `config_kobo_sync` are global. Users' `allowed/denied_column_value` point to a custom column id. | These belong to a library, not to the app. |
| URLs | No library in any URL: `/book/<id>`, `/cover/<id>`, `/read/<id>`, `/download/<id>/<fmt>`, OPDS, `/kobo/<token>/…`. About 170 `url_for` calls, plus ~60 hard-coded paths in `static/js`. | Book ids are only unique within one library, so every link needs a library. |
| Background work | Tasks (`tasks/convert.py`, `metadata_backup.py`, `thumbnail.py`, `mail.py`, `database.py`) create their own `CalibreDB(app)` in a worker thread, with no request. The scheduler (`schedule.py`) runs metadata backup, thumbnails and reconnect for "the" library. | Tasks must carry their library; scheduled jobs must loop over libraries. |
| Requests | One global hook `admin.before_request`. Requests are handled one at a time (tornado's `WSGIContainer`), and `ub.session` is one module-level session. | The current library is chosen in that hook. |

## 2. Design

**Library registry.** An `app.db` table `library` (model `ub.Library`) with these columns:
- `id`, `name`, `slug`, `path`, `split_dir`
- `calibre_uuid`, `enabled`, `sort`

It's filled automatically:
- the classic `config_calibre_dir` becomes the default library (id 1), so a single-library install behaves exactly as before;
- with `CALIBRE_LIBRARY_ROOT` set, every sub-folder of that root containing a `metadata.db` is added.

The code is in `cps/libraries.py`.

**Current library per request**, chosen first in `before_request`, in this order:
1. `?library=<slug>`;
2. the library remembered in the session;
3. the default.

The result is `g.library`. Outside a request, `libraries.use(lib)` sets the library for a background thread.

**Links carry the library.**
- `app.url_defaults` adds `library=<slug>` to every `url_for`, but only when there is more than one library. Single-library URLs are unchanged.
- In each theme's `layout.html`, a `<meta name="cw-library">` tag plus a jQuery `ajaxPrefilter` adds the parameter to the hard-coded AJAX calls.
- The session fallback covers anything else, such as GET forms.

**Per-request database.**
- `CalibreDB.connect()` opens `libraries.current().path`.
- `config.get_book_path()`, `config.library_dir()` and `config.library_is_split()` return the current library's folders.

**Per-user state: a state database per library.** `app.db` is split in two:
- **Shared `app.db`:** what belongs to the app and the people: `user`, `user_session`, `oauthProvider`, `flask_dance_oauth`, `registration`, `remote_auth_token`, `settings`, `library` (and later `user_library`).
- **One state database per library**, `<config dir>/libraries/library-<id>.db`. It holds the book-keyed tables, unchanged: `shelf`, `book_shelf_link`, `shelf_archive`, `book_read_link`, `bookmark`, `archived_book`, `downloads`, `kobo_synced_books`, `kobo_reading_state`, `kobo_bookmark`, `kobo_statistics`, `thumbnail`.

Because each library's book ids live in their own database, **the ~200 queries on these tables need no change**. The change is concentrated in a few places:
1. **`ub.session` routes by table.** A `Session` subclass overrides `get_bind()`: state tables go to the current library's state engine (one cached engine per library), and everything else goes to `app.db`. All code reaches the session as `ub.session`.
2. **Identity map.** It's one long-lived session, and ids of state rows repeat between libraries. So when the library changes, state objects are expunged from the session before the request continues.
3. **`CalibreDB.setup_db`** attaches the current library's state database next to `metadata.db` and `app.db`. The raw-SQL joins in `db.py` (read and archived filters) keep using unqualified table names. Each table exists in exactly one attached database, so SQLite resolves them without ambiguity.
4. **Worker threads:** `ub.init_db_thread()` and `get_new_session_instance()` build the same routing session.
5. **Migration:** an existing install's book-keyed tables are copied from `app.db` into the default library's state database, then dropped from `app.db` (after a backup copy). New libraries get an empty state database. `create_all` on `app.db` is limited to the shared tables.
6. A shelf belongs to its library, which falls out naturally.

*Considered and rejected:*
- **A full `app.db` per library:** users, passwords, OAuth links and settings would be duplicated and drift apart.
- **A `library_id` column on every book table:** it means editing ~200 queries and joins, and every future upstream change to them would need the same edit.

**Access control.**
- A table `user_library(user_id, library_id)` plus a default library per user.
- Admins see all libraries. With no rows, a user sees all libraries, so an upgrade changes nothing.

**Custom columns.** v1 requires the same `custom_columns` set (id, label, datatype) in every library and refuses to add one that differs. Per-library column classes (a separate mapper registry per library) are possible later but are a deep refactor of `db.py`.

**Tasks and scheduler.**
- Every task records its library when created and runs inside `libraries.use(lib)`.
- Scheduled jobs (metadata backup, cover and series thumbnails, reconnect) loop over the enabled libraries.

**OPDS.**
- The root feed lists the libraries as navigation entries when the user can see more than one.
- Feed links carry `?library=`.

**Kobo sync.** v1: each Kobo token is tied to one library (chosen on the user's Kobo settings), and `/kobo/<token>/` routes set `g.library` from the token.

**Google Drive.** It's tied to one library, so it's refused when more than one library is configured.

**UI.**
- A library switcher in the navigation bar of all themes.
- An admin page "Libraries": list, add, discover, enable or disable, reorder, and per-library settings (read column, restricted column, columns to ignore, split dir).
- Search stays within the current library.

## 3. Phases

| Phase | Content | Status |
|---|---|---|
| 0 | Test bed: real server on generated sample libraries (`tests_ml/`) | done |
| 1 | Registry, library per request, links carry the library, switcher | done |
| 2 | State database per library, routing session, migration | done |
| 3 | Tasks, covers and thumbnails, scheduler per library | done |
| 4 | OPDS library navigation, Kobo per library, admin page, user access, custom-column and Google Drive guards | done |
| 5 | Hardening: upgrade test from a real `app.db`, speed check on a large library | next |

Phases 1 and 2 belong together in a release: phase 1 alone shares reading state between libraries.

## 4. Testing

`tests_ml/` starts a real server on two generated libraries whose book ids clash on purpose, and checks:
- that pages, covers, downloads and OPDS come from the right library;
- that a choice is remembered;
- (from phase 2) that reading state never leaks between libraries.

```bash
python -m pytest tests_ml -q
```
