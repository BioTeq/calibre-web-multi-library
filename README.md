# Calibre-Web Multi-Library

A Calibre-Web that serves **several Calibre libraries from one instance**. Users switch libraries in the navigation bar. Each library keeps its own read status, shelves and Kobo sync. OPDS readers see a list of libraries to choose from.

This is an independent, permanent fork of [janeczku/calibre-web](https://github.com/janeczku/calibre-web). It is not meant to be merged back. Upstream changes may be merged into it from time to time. Everything Calibre-Web does still works the same way. With a single library configured, it behaves like regular Calibre-Web.

*Licensed under the GPL v3, like Calibre-Web, which itself is a fork of [library](https://github.com/mutschler/calibreserver).*

## What the fork adds

- **Several libraries in one instance.** Every folder with a Calibre `metadata.db` can be a library. There's a library switcher in the navigation bar of all themes (standard, caliblur, simple). Links name their library (`?library=<name>`), so bookmarks and shared links open the right book.
- **Reading state per library.** Shelves, read status, bookmarks, archive flags, download history, Kobo sync state and cover thumbnails are kept separately for each library. Book 42 in one library never shares its state with book 42 in another.
- **Per-user access.** Admins choose in the user form:
  - which libraries a user may open;
  - which one opens first;
  - which one the user's Kobo syncs with.

  These rules hold for the web interface, OPDS and Kobo alike.
- **OPDS.** `/opds` starts with a list of the libraries. Each library has its own catalog (`/opds?library=<name>`), with working search.
- **Admin page "Libraries".** Rename, reorder, enable or disable, add a library by folder, or look for new ones.
- **Background work per library.** Conversions, sending to e-readers, thumbnails and metadata backup run in the library they belong to. Scheduled jobs run once for every library.

## Setting up libraries

Libraries come from two places:

1. **The classic setting:** Admin → *Edit Calibre Database Configuration* → *Location of Calibre Database*. This library is the default one.
2. **A library root folder** (optional): set the environment variable `CALIBRE_LIBRARY_ROOT` to a folder. Every sub-folder that contains a `metadata.db` is added as a library when Calibre-Web starts, or when you click *Look for new libraries* on the Libraries page. Folders starting with `.` or `_` are skipped.

```
/books                    <- CALIBRE_LIBRARY_ROOT=/books
├── Fiction/metadata.db
├── Non-fiction/metadata.db
└── Comics/metadata.db
```

Libraries can also be added one by one on **Admin → Libraries → Add**. That page also renames them (the display name), orders them (the first enabled library is the default), and enables or disables them. Disabling a library hides it but keeps its reading state.

**Per user:** Admin → edit a user → *Libraries*, *Default Library* and *Library synced with Kobo*. If every library is ticked, the user also gets libraries added later.

### Limits

- **Custom columns must match.** Calibre-Web maps Calibre's custom columns once for all libraries, so every library must have the same custom columns as the default library. A library whose custom columns differ is listed on the Libraries page as *not served*, and the log says why.
- **Google Drive** works with a single library only. While it's enabled, only the default library is served.
- **Search** works within the current library.
- **Do not use the built-in updater** (Admin → *Check for Update*). It installs the upstream Calibre-Web release over this fork. Update by pulling this repository instead.

## Where data is stored

- `app.db` (Calibre-Web's settings database) keeps users, logins, settings and the list of libraries.
- Reading state is stored per library in `libraries/library-<id>.db`, next to `app.db`. Nothing is written into the Calibre library folders for this; they only change when you edit, upload, convert or delete books, as in regular Calibre-Web.

**Upgrading from regular Calibre-Web:**
- On the first start, the existing read status, shelves, bookmarks and Kobo state move into the default library's state database.
- A copy of the old settings database is kept as `app.db.before-multi-library`.
- Users, settings and logins are kept as they are.

## Installation

From source, with Python 3 (developed and tested with Python 3.12):

```bash
git clone -b multi-library https://github.com/BioTeq/calibre-web-multi-library.git
```

```bash
cd calibre-web-multi-library && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
CALIBRE_LIBRARY_ROOT=/path/to/libraries .venv/bin/python cps.py -p /path/to/config/app.db
```

Then open `http://localhost:8083` and log in as `admin` / `admin123`, and change that password. Set the default library under Admin → *Edit Calibre Database Configuration*.

Optional extras are the same as for Calibre-Web: `optional-requirements.txt`, ImageMagick for covers, Calibre's `ebook-convert` for conversions, and kepubify for Kobo.

### Docker

Every push to the `multi-library` branch builds `ghcr.io/bioteq/calibre-web-multi-library` (amd64 and arm64). The build is smoke-tested on two sample libraries before it is published. Tags: `latest`, plus `sha-<commit>` to pin a version. (The `pip install calibreweb` package and the linuxserver.io image are upstream Calibre-Web, not this fork.)

```yaml
services:
  calibre-web:
    image: ghcr.io/bioteq/calibre-web-multi-library:latest
    container_name: calibre-web
    environment:
      - PUID=1000                        # files are written as this user/group
      - PGID=1000
      - TZ=Europe/Berlin
      - CALIBRE_DEFAULT_LIBRARY=Fiction  # optional: folder under /books opened first (else the first one)
      # - CALIBRE_WEB_PORT=8083          # optional: listening port (default 8083)
    volumes:
      - /path/to/config:/config          # settings, reading state per library, cache, log
      - /path/to/libraries:/books        # every sub-folder with a metadata.db is a library
    ports:
      - 8083:8083
    restart: unless-stopped
```

Optional: `CALIBRE_ADMIN_PASSWORD` sets the admin password on the very first start, instead of the well-known `admin123`. Remove it from the stack afterwards.

The image includes ImageMagick (covers) and kepubify (Kobo). It does not include Calibre's `ebook-convert`, so there are no format conversions unless you add it. To update, re-pull the image and recreate the container.

### Security notes

- **The image:**
  - The app runs as `PUID:PGID`, not as root.
  - The image is rebuilt weekly with the base image's security updates.
  - kepubify is a pinned, checksum-verified release, and the build actions are pinned to commits.
  - Every build is smoke-tested in a hardened container (read-only root filesystem, `no-new-privileges`, reduced capabilities) before it is published. The same options work in a stack:
    ```yaml
        read_only: true
        tmpfs: [/tmp]
        security_opt: [no-new-privileges:true]
        cap_drop: [ALL]
        cap_add: [CHOWN, SETUID, SETGID, DAC_OVERRIDE, FOWNER]
    ```
- **Exposure:** don't publish Calibre-Web directly to the internet. Its OPDS and Kobo endpoints use passwords or tokens over plain HTTP. For access from outside, use a VPN, or a reverse proxy with HTTPS.
- **Mounts:** mount only the library folders Calibre-Web needs (one bind mount per library under `/books`), not a whole share.
- **Accounts:** after the first start, set your own admin password, turn off anonymous browsing and public registration unless you need them, and give each user only the libraries they need.
- **Updates:** the self-updater is disabled in this fork. Update by re-pulling the image.

## Tests

`tests_ml/` starts a real server on generated sample libraries whose book ids clash on purpose. It checks that pages, covers, downloads, OPDS, Kobo, reading state, access rules, background jobs and upgrades all stay in their own library.

```bash
pip install pytest && python -m pytest tests_ml -q
```

To try it out by hand on three generated sample libraries (nothing of yours is touched):

```bash
python tests_ml/demo.py
```

This starts Calibre-Web on `http://127.0.0.1:8090`; log in as `admin` / `admin123`. The demo libraries are created in `./cw-demo`.

The design and the remaining work are described in [MULTI_LIBRARY_PLAN.md](MULTI_LIBRARY_PLAN.md).

## Everything else

All other features, settings and troubleshooting are those of Calibre-Web. See the [Calibre-Web wiki](https://github.com/janeczku/calibre-web/wiki). Report problems with multi-library features in this repository's issues, not upstream.

Thanks to the [Calibre-Web contributors](https://github.com/janeczku/calibre-web/graphs/contributors), on whose work this fork stands.
