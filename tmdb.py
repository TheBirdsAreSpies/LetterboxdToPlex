import json
import urllib.parse
import requests

import config
import sqlite3

from enum import Enum
from datetime import datetime


class ReleaseType(Enum):
    PREMIERE = 1
    THEATRICAL_LIMITED = 2
    THEATRICAL = 3
    DIGITAL = 4
    PHYSICAL = 5
    TV = 6


class ReleaseDate:
    def __init__(self, data):
        self.certification = data.get("certification", "")
        self.descriptors = data.get("descriptors", [])
        self.iso_639_1 = data.get("iso_639_1", "")
        self.note = data.get("note", "")
        self.release_date = datetime.fromisoformat(data["release_date"].replace("Z", "+00:00"))
        self.type = data.get("type", 0)


class ReleaseCountry:
    def __init__(self, data):
        self.iso_3166_1 = data.get("iso_3166_1", "")
        self.release_dates = [ReleaseDate(rd) for rd in data.get("release_dates", [])]

    def __repr__(self):
        return f'{self.iso_3166_1}: {self.release_dates}'


class MovieReleaseInfo:
    def __init__(self, data):
        self.id = data.get("id", 0)
        self.results = [ReleaseCountry(rc) for rc in data.get("results", [])]


class Movie:
    def __init__(self, data):
        self.adult = data.get("adult") or ""
        self.backdrop_path = data.get("backdrop_path") or ""
        self.genre_ids = data.get("genre_ids") or ""
        self.id = data.get("id") or ""
        self.original_language = data.get("original_language") or ""
        self.original_title = data.get("original_title") or ""
        self.overview = data.get("overview") or ""
        self.popularity = data.get("popularity") or ""
        self.poster_path = data.get("poster_path") or ""
        self.release_date = data.get("release_date") or ""
        self.title = data.get("title") or ""
        self.video = data.get("video") or ""
        self.vote_average = data.get("vote_average") or ""
        self.vote_count = data.get("vote_count") or ""


class MovieResponse:
    def __init__(self, data):
        self.page = data.get("page")
        self.results = [Movie(item) for item in data.get("results", [])]
        self.total_pages = data.get("total_pages")
        self.total_results = data.get("total_results")


class Translation:
    def __init__(self, data):
        self.iso_3166_1 = data.get("iso_3166_1")
        self.iso_639_1 = data.get("iso_639_1")
        self.name = data.get("name")
        self.english_name = data.get("english_name")
        self.data = Movie(data.get("data"))


class MovieTranslation:
    def __init__(self, data):
        self.id = data.get("id")
        self.translations = [Translation(item) for item in data.get("translations", [])]

    def get_translation_by_iso(self):
        return next((t for t in self.translations if t.iso_3166_1 == config.tmdb_language_code), None)


class MovieDetails:
    def __init__(self, data):
        self.adult = data.get("adult")
        self.backdrop_path = data.get("backdrop_path")
        self.belongs_to_collection = data.get("belongs_to_collection")
        self.budget = data.get("budget")
        self.genres = data.get("genres")
        self.homepage = data.get("homepage")
        self.id = data.get("id")
        self.imdb_id = data.get("imdb_id")
        self.origin_country = data.get("origin_country")
        self.original_language = data.get("original_language")
        self.original_title = data.get("original_title")
        self.overview = data.get("overview")
        self.popularity = data.get("popularity")
        self.poster_path = data.get("poster_path")
        self.production_companies = data.get("production_companies")
        self.production_countries = data.get("production_countries")
        self.release_date = data.get("release_date")
        self.revenue = data.get("revenue")
        self.runtime = data.get("runtime")
        self.spoken_languages = data.get("spoken_languages")
        self.status = data.get("status")
        self.tagline = data.get("tagline")
        self.title = data.get("title")
        self.video = data.get("video")
        self.vote_average = data.get("vote_average")
        self.vote_count = data.get("vote_count")


def __release_type_name(value):
    normalized = __normalize_release_type_value(value)
    for release_type in ReleaseType:
        if str(release_type.value) == normalized:
            return release_type.name
    return str(value)


def __normalize_release_type_value(value):
    if isinstance(value, ReleaseType):
        return str(value.value)

    if isinstance(value, int):
        return str(value)

    if isinstance(value, str):
        candidate = value.strip()
        if candidate.isdigit():
            return candidate

        if "." in candidate:
            candidate = candidate.split(".")[-1]

        if candidate in ReleaseType.__members__:
            return str(ReleaseType[candidate].value)

        return candidate

    return str(value)


def __parse_release_datetime(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def __ensure_tmdb_releases_schema(cursor):
    cursor.execute("PRAGMA table_info(tmdb_releases)")
    columns = {row[1] for row in cursor.fetchall()}

    if "iso_3166_1" not in columns:
        cursor.execute("ALTER TABLE tmdb_releases ADD COLUMN iso_3166_1 TEXT NOT NULL DEFAULT ''")

    if "release_type_name" not in columns:
        cursor.execute("ALTER TABLE tmdb_releases ADD COLUMN release_type_name TEXT NOT NULL DEFAULT ''")


def __store_release_dates(movie_id: str, movie_release_info: MovieReleaseInfo):
    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()

    # Keep a single authoritative snapshot per TMDB id.
    cursor.execute('DELETE FROM tmdb_releases WHERE tmdb_id = ?', (movie_id,))

    insert_query = ('INSERT INTO tmdb_releases '
                    '(title, iso_3166_1, release_id, release_type_name, release_date, tmdb_id) '
                    'VALUES (?, ?, ?, ?, ?, ?)')

    for country in movie_release_info.results:
        for rd in country.release_dates:
            cursor.execute(insert_query, (
                movie_id,
                country.iso_3166_1,
                int(rd.type),
                __release_type_name(rd.type),
                str(rd.release_date),
                movie_id,
            ))

    connection.commit()
    cursor.close()
    connection.close()


def get_release_dates(movie_id: str):
    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()

    select_query = ('SELECT iso_3166_1, release_id, release_type_name, release_date '
                    'FROM tmdb_releases WHERE tmdb_id = ? ORDER BY release_date ASC')
    cursor.execute(select_query, (movie_id,))
    rows = cursor.fetchall()

    cursor.close()
    connection.close()

    return [
        {
            "country_code": row[0],
            "release_type_id": row[1],
            "release_type": row[2],
            "release_date": row[3],
        }
        for row in rows
    ]


def get_release_dates_for_letterboxd_movie(lb_title: str, lb_year: str):
    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()

    cursor.execute('SELECT tmdb_id FROM tmdb_cache WHERE lb_title = ? AND lb_year = ? LIMIT 1', (lb_title, str(lb_year)))
    row = cursor.fetchone()

    cursor.close()
    connection.close()

    if not row or not row[0]:
        return None, []

    movie_id = str(row[0])
    return movie_id, get_release_dates(movie_id)


def get_release_dates_for_letterboxd_movie_with_fetch(lb_title: str, lb_year: str):
    """
    Gets release dates for a Letterboxd movie. If no cached releases exist,
    fetches them from TMDB API on-demand.

    Returns: (movie_id, releases_list) tuple
    """
    # First try to get cached releases
    movie_id, releases = get_release_dates_for_letterboxd_movie(lb_title, lb_year)

    if releases:
        # Already have cached releases
        return movie_id, releases

    if not movie_id:
        # No TMDB ID found, nothing to fetch
        return None, []

    # Fetch release dates from API and store them
    release_date(movie_id)

    # Now get the freshly fetched and stored releases
    return movie_id, get_release_dates(movie_id)


def get_tmdb_id_for_letterboxd_movie(lb_title: str, lb_year: str):
    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()

    cursor.execute('SELECT tmdb_id FROM tmdb_cache WHERE lb_title = ? AND lb_year = ? LIMIT 1', (lb_title, str(lb_year)))
    row = cursor.fetchone()

    cursor.close()
    connection.close()

    if not row or not row[0]:
        return None

    movie_id = str(row[0]).strip()
    if not movie_id or movie_id in {"-1", "None", "null"}:
        return None
    return movie_id


def get_configured_release_date_for_movie(movie_id: str, refresh: bool = False):
    if not movie_id:
        return None

    movie_id = str(movie_id).strip()
    if not movie_id or movie_id in {"-1", "None", "null"}:
        return None

    if refresh:
        release_date(movie_id)

    releases = get_release_dates(movie_id)
    if not releases:
        release_date(movie_id)
        releases = get_release_dates(movie_id)

    return get_configured_release_date(releases)


def get_configured_release_date(releases_list):
    """Return the earliest release date matching configured country + type."""
    if not releases_list:
        return None

    country_code = str(getattr(config, "tmdb_release_country_code", "")).strip().upper()
    release_type_value = __normalize_release_type_value(getattr(config, "tmdb_release_type", ""))

    candidates = []
    for rel in releases_list:
        rel_country = str(rel.get("country_code", "")).strip().upper()
        rel_type = __normalize_release_type_value(rel.get("release_type_id", rel.get("release_type", "")))
        rel_date = rel.get("release_date")
        parsed_date = __parse_release_datetime(rel_date)

        if parsed_date is None:
            continue
        if country_code and rel_country != country_code:
            continue
        if release_type_value and rel_type != release_type_value:
            continue

        candidates.append((parsed_date, str(rel_date)))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def get_first_release_per_type(releases_list):
    """Return one earliest entry per release type."""
    if not releases_list:
        return []

    best_by_type = {}

    for rel in releases_list:
        rel_date = rel.get("release_date")
        parsed_date = __parse_release_datetime(rel_date)
        if parsed_date is None:
            continue

        rel_type_raw = rel.get("release_type_id", rel.get("release_type", ""))
        rel_type_normalized = __normalize_release_type_value(rel_type_raw)
        rel_type_key = rel_type_normalized or str(rel.get("release_type", ""))
        if not rel_type_key:
            continue
        existing = best_by_type.get(rel_type_key)

        if existing is None:
            best_by_type[rel_type_key] = (parsed_date, rel)
            continue

        existing_date, _ = existing
        if parsed_date < existing_date:
            best_by_type[rel_type_key] = (parsed_date, rel)

    reduced = [entry[1] for entry in best_by_type.values()]

    def _sort_key(entry):
        normalized = __normalize_release_type_value(entry.get("release_type_id", entry.get("release_type", "")))
        if normalized.isdigit():
            return 0, int(normalized)
        return 1, str(entry.get("release_type", ""))

    return sorted(reduced, key=_sort_key)


def release_date(movie_id: str):
    url = f"https://api.themoviedb.org/3/movie/{movie_id}/release_dates"
    headers = __get_headers()
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return None

    data = json.loads(response.text)
    movie_release_info = MovieReleaseInfo(data)
    __store_release_dates(movie_id, movie_release_info)

    releases = get_release_dates(movie_id)
    return get_configured_release_date(releases)


def __get_headers():
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {config.tmdb_api_key}"
    }

    return headers


def drop_table():
    create_table_query = 'DROP TABLE tmdb_cache'

    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()
    cursor.execute(create_table_query)
    connection.commit()
    connection.close()


def create_table():
    create_table_query = '''
    CREATE TABLE IF NOT EXISTS tmdb_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lb_title TEXT NOT NULL,
        lb_year TEXT NOT NULL,
        tmdb_translated_title TEXT NOT NULL,
        tmdb_release_date DATE NOT NULL,
        tmdb_id TEXT NOT NULL,
        imdb_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    '''

    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()
    cursor.execute(create_table_query)

    create_table_query = '''
    CREATE TABLE IF NOT EXISTS tmdb_releases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        iso_3166_1 TEXT NOT NULL DEFAULT '',
        release_id INTEGER NOT NULL,
        release_type_name TEXT NOT NULL DEFAULT '',
        release_date DATE NOT NULL,
        tmdb_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    '''
    cursor = connection.cursor()
    cursor.execute(create_table_query)

    __ensure_tmdb_releases_schema(cursor)

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tmdb_releases_tmdb_id ON tmdb_releases (tmdb_id);')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tmdb_releases_country_type ON tmdb_releases (iso_3166_1, release_id);')

    connection.commit()
    connection.close()


def reorganize_indexes():
    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()
    cursor.execute('DROP INDEX IF EXISTS idx_tmdb_id;')
    cursor.execute('CREATE INDEX idx_tmdb_id ON tmdb_cache (tmdb_id);')
    cursor.execute('DROP INDEX IF EXISTS idx_lb_title_year;')
    cursor.execute('CREATE INDEX idx_lb_title_year ON tmdb_cache (lb_title, lb_year);')
    cursor.execute('DROP INDEX IF EXISTS idx_translated_title_release_date;')
    cursor.execute('CREATE INDEX idx_translated_title_release_date ON tmdb_cache '
                   '(tmdb_translated_title, tmdb_release_date);')
    connection.commit()

    cursor.close()
    connection.close()


def __get_cached(title: str, year: int, lb: bool):
    if lb:
        select_query = 'SELECT * FROM tmdb_cache WHERE lb_title = ? AND lb_year = ?'
    else:
        select_query = 'SELECT * FROM tmdb_cache WHERE tmdb_translated_title = ? AND tmdb_release_date = ?'

    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()
    cursor.execute(select_query, (title, year))

    rs = cursor.fetchone()
    cursor.close()
    connection.close()

    if rs:
        data = {}
        cached = Movie(data)
        cached.title = rs[3]  # 'tmdb_translated_title'
        cached.release_date = str(rs[4])  # 'tmdb_release_date'
        cached.id = str(rs[5])  # tmdb_id
        cached.imdb_id = str(rs[6])  # imdb_id
        return cached

    return None


def get_imdb_id(movie_id: str):
    select_query = 'SELECT imdb_id FROM tmdb_cache WHERE tmdb_id = ?'

    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()
    cursor.execute(select_query, (movie_id,))

    rs = cursor.fetchone()
    cursor.close()
    connection.close()

    if rs:
        return str(rs[0])

    return None


def store_movie_to_cache(tmdb_translated_title: str, tmdb_release_date: str,
                         lb_title: str, lb_date: str, tmdb_id: str = None):
    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()

    select_query = 'SELECT * FROM tmdb_cache WHERE lb_title = ? AND lb_year = ?'
    cursor.execute(select_query, (lb_title, lb_date))
    rs = cursor.fetchone()

    if not rs:
        details = __get_movie_details(tmdb_id)
        imdb_id = details.imdb_id

        insert_query = ('INSERT INTO tmdb_cache (lb_title, lb_year, '
                        'tmdb_translated_title, tmdb_release_date, tmdb_id, imdb_id) '
                        'VALUES (?, ?, ?, ?, ?, ?)')
        cursor.execute(insert_query, (lb_title, lb_date,
                                      tmdb_translated_title, tmdb_release_date, tmdb_id, imdb_id))
        connection.commit()

    cursor.close()
    connection.close()


def invalidate_cache():
    if not config.tmdb_invalidate_cache:
        return

    try:
        days = int(config.tmdb_invalidate_cache_days)
    except Exception:
        days = 30

    if days < 0:
        days = 0

    connection = sqlite3.connect(config.db_path)
    cursor = connection.cursor()

    cursor.execute(
        "DELETE FROM tmdb_cache WHERE created_at < DATETIME('now', ?)",
        (f"-{days} days",),
    )
    cursor.execute(
        "DELETE FROM tmdb_releases WHERE created_at < DATETIME('now', ?)",
        (f"-{days} days",),
    )
    connection.commit()

    cursor.close()
    connection.close()


def auth():
    url = "https://api.themoviedb.org/3/authentication"
    headers = __get_headers()

    response = requests.get(url, headers=headers)
    return "Success." in response.text


def search_movie(title: str, year: int = None):
    if config.tmdb_cache:
        found = __get_cached(title, year, True)
        if found:
            return [found]

    compiled_title = urllib.parse.quote(title)
    if year is not None:
        url = (f'https://api.themoviedb.org/3/search/movie?query={compiled_title}&include_adult=true'
               f'&language=en-US&primary_release_year={year}&page=1')
    else:
        url = (f'https://api.themoviedb.org/3/search/movie?query={compiled_title}&include_adult=true'
               f'&language=en-US&page=1')
    headers = __get_headers()
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return []

    data = json.loads(response.text)
    movies = MovieResponse(data)

    return movies.results




def __get_movie_details(movie_id: str):
    url = f"https://api.themoviedb.org/3/movie/{movie_id}?language=en-US"
    headers = __get_headers()

    response = requests.get(url, headers=headers)

    data = json.loads(response.text)
    details = MovieDetails(data)

    return details


def translation(movie: Movie):
    if config.tmdb_cache:
        found = __get_cached(movie.title, movie.release_date, False)
        if found:
            return found.title

    url = f"https://api.themoviedb.org/3/movie/{movie.id}/translations"
    headers = __get_headers()
    response = requests.get(url, headers=headers)

    data = json.loads(response.text)
    movie_translation = MovieTranslation(data)

    filtered_lang = movie_translation.get_translation_by_iso()
    if filtered_lang is None or filtered_lang.data is None or len(filtered_lang.data.title) == 0:
        return movie.original_title

    return filtered_lang.data.title
