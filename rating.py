import autoselection
import config
import csv
import logging
import matching
import util
import sqlite3

from mapping import Mapping
from movie import Movie
from ignoremovie import IgnoreMovie
from missingmovie import MissingMovie
from tqdm import tqdm


def rating(plex, movies, logger: logging.Logger, progress_callback=None):
    to_ignore = IgnoreMovie.load_json() or []
    missing = MissingMovie.load_json() or []
    autoselector = autoselection.AutoSelection.load_json() or []
    mapping = Mapping.load_json() or []

    data = _read_ratings_csv_()
    publish_progress = util.progress_publisher(logger, progress_callback)

    connection = sqlite3.connect(config.db_path)
    try:
        cursor = connection.cursor()
        _create_table(cursor)
        connection.commit()

        with tqdm(total=len(data), unit='Movies') as pbar:
            for name, year, stars, uri in data:
                pbar.set_description(f'Processing {name} ({year})'.ljust(80, ' '))
                publish_progress(f'Processing {name} ({year})')

                # ratings are stored by the letterboxd entry, before any mapping or translation is applied
                lb_name = name
                lb_year = year

                was_missing_names = []
                combination = Movie(name, year)
                was_missing_names.append(combination.name)

                if any(combination.name == existing.name and combination.year == existing.year for existing in
                       to_ignore):  # movie is in ignore list, maybe remove due to the second check after mapping
                    pbar.update(1)
                    continue

                mapped = util.find_movie_by_letterboxd_title(mapping, combination)
                if mapped:
                    if mapped.year > -1:
                        year = mapped.year
                    combination = Movie(mapped.plex_title, year)
                    name = combination.name

                was_missing_names.append(name)

                calculated_rating = float(stars) * 2

                cursor.execute('SELECT rating FROM ratings WHERE title = ? AND year = ?', (lb_name, lb_year))
                rs = cursor.fetchone()
                if rs and rs[0] == calculated_rating:
                    # Keep missing list in sync even when the rating write is skipped.
                    missing = util.remove_from_missing_if_needed(missing, was_missing_names)
                    logger.debug(f'Movie {name} is already rated as {calculated_rating} - SKIP')
                    pbar.update(1)
                    continue

                if config.tmdb_use_api:
                    tmdb_id, tmdb_name, tmdb_year = matching.lookup_tmdb(name, year, uri, logger)

                    # seems like a tv show, skip
                    if tmdb_name is None:
                        pbar.update(1)
                        continue

                    name = tmdb_name
                    year = tmdb_year
                    movie = matching.find_by_tmdb_id(movies, name, tmdb_id, autoselector, combination, logger)
                else:
                    movie = matching.find_by_title(movies, name, year, autoselector, combination, logger)

                if not movie:
                    logger.info(f'Movie {name} ({year}) is missing')
                    if util.find_missing(missing, combination) is None:
                        logger.debug(f'Movie {name} ({year}) added to missing list')
                        missing.append(combination)

                    pbar.update(1)
                    continue

                logger.info(f'Found {movie.title} ({movie.year}), will rate')
                was_missing_names.append(movie.title)
                missing = util.remove_from_missing_if_needed(missing, was_missing_names)

                movie.rate(calculated_rating)

                logger.debug(f'Storing row: Rating: {calculated_rating} Title: {lb_name} ({lb_year})')
                cursor.execute('INSERT INTO ratings (title, year, rating) VALUES (?, ?, ?) '
                               'ON CONFLICT(title, year) DO UPDATE SET rating = excluded.rating',
                               (lb_name, lb_year, calculated_rating))
                connection.commit()

                pbar.update(1)
    finally:
        connection.close()

    IgnoreMovie.store_json(to_ignore)
    MissingMovie.store_json(missing)
    autoselection.AutoSelection.store_json(autoselector)
    publish_progress('All ratings imported')


def _create_table(cursor):
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        rating REAL
    )
    ''')

    cursor.execute('PRAGMA table_info(ratings)')
    columns = {row[1] for row in cursor.fetchall()}
    if 'year' not in columns:
        # old rows were keyed by title only (partly by translated titles) and are not reliable, start over
        cursor.execute("ALTER TABLE ratings ADD COLUMN year TEXT NOT NULL DEFAULT ''")
        cursor.execute('DELETE FROM ratings')

    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_ratings_title_year ON ratings (title, year)')


def _read_ratings_csv_():
    file_path = config.ratings_path
    data = []

    resolved_path = util.resolve_existing_path(file_path)
    if not resolved_path:
        raise FileNotFoundError(f"Ratings CSV not found: {file_path}")

    with open(resolved_path, 'r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        next(reader)  # skip header
        for row in reader:
            date, name, year, uri, stars = row
            data.append((name, year, stars, uri))
    return data
