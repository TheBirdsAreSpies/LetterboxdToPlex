import json
import urllib.parse
import requests
import config
import sqlite3


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


def __get_headers():
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {config.tmdb_api_key}"
    }

    return headers


def drop_table():
    create_table_query = 'DROP TABLE tmdb_cache'

    connection = sqlite3.connect('ltp.db')
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

    connection = sqlite3.connect('ltp.db')
    cursor = connection.cursor()
    cursor.execute(create_table_query)
    connection.commit()
    connection.close()


def reorganize_indexes():
    connection = sqlite3.connect('ltp.db')
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

    connection = sqlite3.connect('ltp.db')
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

    connection = sqlite3.connect('ltp.db')
    cursor = connection.cursor()
    cursor.execute(select_query, (movie_id,))

    rs = cursor.fetchone()
    cursor.close()
    connection.close()

    if rs:
        return str(rs[0])

    return None


def store_to_cache(tmdb_translated_title: str, tmdb_release_date: str,
                   lb_title: str, lb_date: str, tmdb_id: str = None):
    connection = sqlite3.connect('ltp.db')
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

    connection = sqlite3.connect('ltp.db')
    cursor = connection.cursor()

    cursor.execute(f"""
                    DELETE FROM tmdb_cache
                    WHERE created_at < DATE('now', '-{config.tmdb_invalidate_cache_days} days');
                    """)
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
