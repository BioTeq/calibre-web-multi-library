"""Build small Calibre libraries for the multi-library tests from the empty template library/metadata.db.

Every library gets books with ids 1, 2, 3... (so ids clash between libraries, on purpose), an EPUB file and a
cover per book. Titles are invented and contain the library's name, so a test can see which library answered.
"""
import os, shutil, sqlite3, uuid, zipfile
from datetime import datetime, timezone

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'library', 'metadata.db')

# a 1x1 white JPEG; a comment segment per library/book makes every cover file different
JPEG_HEAD = bytes.fromhex('ffd8ffe000104a46494600010100000100010000')
JPEG_BODY = bytes.fromhex(
    'ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30'
    '313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f0000010501010101010100000000000000000102030405'
    '060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c1'
    '1552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a7374'
    '75767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6'
    'd7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbd3ffd9')


def jpeg(tag):
    c = tag.encode()
    return JPEG_HEAD + b'\xff\xfe' + (len(c) + 2).to_bytes(2, 'big') + c + JPEG_BODY


def epub(path, title, author):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml', '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="c.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr('c.opf', f'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
                   f'unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{title}'
                   f'</dc:title><dc:creator>{author}</dc:creator><dc:identifier id="id">{uuid.uuid4()}</dc:identifier>'
                   '<dc:language>en</dc:language></metadata><manifest><item id="t" href="t.html" '
                   'media-type="application/xhtml+xml"/></manifest><spine><itemref idref="t"/></spine></package>')
        z.writestr('t.html', f'<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>{title}</h1>'
                   + '<p>Sample text.</p>' * 200 + '</body></html>')


def build(folder, name, titles, author='Sample Author'):
    """Create a Calibre library in folder/name with one EPUB book per title. Returns the library path."""
    lib = os.path.join(folder, name)
    os.makedirs(lib)
    shutil.copy(TEMPLATE, os.path.join(lib, 'metadata.db'))
    c = sqlite3.connect(os.path.join(lib, 'metadata.db'))
    c.create_function('title_sort', 1, lambda t: t)
    c.create_function('uuid4', 0, lambda: str(uuid.uuid4()))
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S+00:00')
    c.execute('insert into authors(name, sort) values (?, ?)', (author, author))
    author_id = c.execute('select id from authors where name=?', (author,)).fetchone()[0]
    for i, title in enumerate(titles, 1):
        rel = f'{author}/{title} ({i})'
        os.makedirs(os.path.join(lib, rel))
        fname = title
        epub(os.path.join(lib, rel, fname + '.epub'), title, author)
        open(os.path.join(lib, rel, 'cover.jpg'), 'wb').write(jpeg(f'{name}/{i}'))
        c.execute('insert into books(id, title, sort, author_sort, timestamp, pubdate, series_index, path, has_cover, '
                  'last_modified) values (?,?,?,?,?,?,1.0,?,1,?)', (i, title, title, author, now, now, rel, now))
        c.execute('insert into books_authors_link(book, author) values (?, ?)', (i, author_id))
        c.execute('insert into data(book, format, uncompressed_size, name) values (?, ?, ?, ?)',
                  (i, 'EPUB', os.path.getsize(os.path.join(lib, rel, fname + '.epub')), fname))
    c.commit(); c.close()
    return lib
