import requests
import sqlite3
import config

from letterboxdpy.movie import Movie


def __letterboxd_movie_from_slug(slug):
    movie = Movie(slug)
    return movie


def ids_from_slug(slug):
    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()

    select_query = 'SELECT * FROM letterboxd_cache WHERE slug = ?'
    cursor.execute(select_query, (slug,))
    rs = cursor.fetchone()

    if rs and rs[4] is not None:
        return [rs[4], rs[5]]
    else:
        try:
            lb_movie = __letterboxd_movie_from_slug(slug)
            tmdb_url = lb_movie.tmdb_link
            parts = tmdb_url.split("/")
            tmdb_id = parts[len(parts) - 2]

            imdb_url = lb_movie.imdb_link
            if imdb_url is not None:
                parts = imdb_url.split("/")
                imdb_id = parts[len(parts) - 2]
            else:
                imdb_id = None

            set_tmdb_id(slug, tmdb_id, imdb_id)
            return [tmdb_id, imdb_id]
        except Exception:
            return [-1, -1]


def slug_from_short_url(uri):
    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()

    select_query = 'SELECT * FROM letterboxd_cache WHERE short_url = ?'
    cursor.execute(select_query, (uri,))
    rs = cursor.fetchone()

    if not rs:
        long_url = __get_redirected_url(uri)
        parts = long_url.split('/')
        slug = parts[len(parts) - 2]

        store_to_cache(slug, uri, long_url)
        return slug
    else:
        return rs[2]


def __get_redirected_url(url) -> str:
    response = requests.head(url, allow_redirects=True)
    return response.url


def create_table():
    create_table_query = '''
    CREATE TABLE IF NOT EXISTS letterboxd_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        short_url TEXT NOT NULL,
        slug TEXT NOT NULL,
        long_url TEXT NOT NULL,
        tmdb_id TEXT NULL,
        imdb_id TEXT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    '''

    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()
    cursor.execute(create_table_query)
    connection.commit()
    connection.close()


def short_to_long_url(short_url: str) -> str:
    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()

    select_query = 'SELECT * FROM letterboxd_cache WHERE short_url = ?'
    cursor.execute(select_query, (short_url,))
    rs = cursor.fetchone()

    if rs:
        return rs[3]


def store_to_cache(slug: str, short_url: str, long_url: str, tmdb_id: str = None):
    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()

    select_query = 'SELECT * FROM letterboxd_cache WHERE slug = ?'
    cursor.execute(select_query, (slug,))
    rs = cursor.fetchone()

    if not rs:
        insert_query = 'INSERT INTO letterboxd_cache (short_url, slug, long_url, tmdb_id) VALUES (?, ?, ?, ?)'
        cursor.execute(insert_query, (short_url, slug, long_url, tmdb_id))
        connection.commit()

    cursor.close()
    connection.close()


def set_tmdb_id(slug: str, tmdb_id: str, imdb_id: str):
    try:
        connection = sqlite3.connect(config.db_path)
        cursor = connection.cursor()

        update_query = 'UPDATE letterboxd_cache SET tmdb_id = ?, imdb_id = ? WHERE slug = ?'
        cursor.execute(update_query, (tmdb_id, imdb_id, slug))
        connection.commit()

        cursor.close()
        connection.close()
    except sqlite3.Error:
        pass
