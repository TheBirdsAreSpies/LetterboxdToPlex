import plexapi.video
import autoselection
import config
import csv
import logging
import util
import sqlite3

from mapping import Mapping
from movie import Movie
from ignoremovie import IgnoreMovie
from missingmovie import MissingMovie
from tqdm import tqdm


def rating(plex, movies, logger: logging.Logger):
    to_ignore = IgnoreMovie.load_json() or []
    missing = MissingMovie.load_json() or []
    autoselector = autoselection.AutoSelection.load_json() or []
    mapping = Mapping.load_json() or []

    data = _read_ratings_csv_()

    connection = sqlite3.connect('ltp.db')
    cursor = connection.cursor()

    create_table_query = '''
    CREATE TABLE IF NOT EXISTS ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        rating REAL
    )
    '''

    logger.debug('Creating table')
    cursor.execute(create_table_query)
    connection.commit()

    with tqdm(total=len(data), unit='Movies') as pbar:
        for name, year, stars in data:
            pbar.set_description(f'Processing {name} ({year})'.ljust(80, ' '))

            was_missing_names = []
            combination = Movie(name, year)

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

            calculated_rating = float(stars) * 2

            select_query = 'SELECT 1 FROM ratings WHERE title = ? AND rating = ?'
            cursor.execute(select_query, (name, calculated_rating))
            rs = cursor.fetchone()
            if rs:
                logger.debug(f'Movie {name} is already rated as {calculated_rating} - SKIP')
                pbar.update(1)
                continue

            years = [year, str(int(year) - 1), str(int(year) + 1)]
            result = movies.search(title=name, year=years)

            if len(result) == 1:
                movie: plexapi.video.Movie = result[0]
                missing = util.remove_from_missing_if_needed(missing, was_missing_names)

            elif len(result) > 1:
                counter = 1
                preselection = util.find_preselection(autoselector, combination, result)

                logger.info(f'Found multiple movies for {name} ({year}):')
                if preselection:
                    logger.info(f'Auto selected {preselection.title} ({preselection.year})')

                    movie = preselection
                    was_missing_names.append(preselection.title)
                    missing = util.remove_from_missing_if_needed(missing, was_missing_names)
                else:
                    print(f'\nFound multiple movies for {name} ({year}):')

                    for movie in result:
                        if movie.editionTitle is None:
                            logger.info(f'{counter}: {movie.title} ({movie.year})')
                            print(f'{counter}: {movie.title} ({movie.year})')
                        else:
                            logger.info(f'{counter}: {movie.title} ({movie.year}, {movie.editionTitle})')
                            print(f'{counter}: {movie.title} ({movie.year}, {movie.editionTitle})')
                        counter += 1

                    selection = int(input('Use:'))
                    if 0 < selection < len(result) + 1:
                        res = result[selection - 1]
                        movie: plexapi.video.Movie = res
                        selector = autoselection.AutoSelection(combination, res.key)
                        autoselector.append(selector)
                        autoselection.AutoSelection.store_json(autoselector)
                        was_missing_names.append(res.title)
                        missing = util.remove_from_missing_if_needed(missing, was_missing_names)

            else:
                is_present = any(
                    combination.name == existing.name and combination.year == existing.year for existing in missing)
                if not is_present:
                    missing.append(combination)

                pbar.update(1)
                continue

            movie.rate(calculated_rating)
            if rs:
                existing_rating = result[0]
                if existing_rating != calculated_rating:
                    logger.debug(f'Updating row: Rating: {calculated_rating} Title: {name}')
                    update_query = 'UPDATE ratings SET rating = ? WHERE title = ?'
                    cursor.execute(update_query, (calculated_rating, name))
                    connection.commit()
                    logger.debug('Updated')
            else:
                logger.debug(f'Inserting row row: Rating: {calculated_rating} Title: {name}')
                insert_query = 'INSERT INTO ratings (title, rating) VALUES (?, ?)'
                cursor.execute(insert_query, (name, calculated_rating))
                connection.commit()
                logger.debug('Inserted')

            pbar.update(1)

        IgnoreMovie.store_json(to_ignore)
        MissingMovie.store_json(missing)
        autoselection.AutoSelection.store_json(autoselector)
        logger.info('All ratings imported.')


def _read_ratings_csv_():
    file_path = config.ratings_path
    data = []

    with open(file_path, 'r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        next(reader)  # skip header
        for row in reader:
            date, name, year, uri, stars = row
            data.append((name, year, stars))
    return data
