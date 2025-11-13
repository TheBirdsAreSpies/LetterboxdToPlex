import plexapi.video
import autoselection
import config
import csv
import logging
import util
import sqlite3
import tmdb
import letterboxd
from selector import choose_movie

from plexapi.exceptions import NotFound
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

    connection = sqlite3.connect(config.db_path)
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
        for name, year, stars, uri in data:
            pbar.set_description(f'Processing {name} ({year})'.ljust(80, ' '))
            progress_callback(f'Processing {name} ({year})')

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

            if config.tmdb_use_api:
                logger.debug(f'Trying to look it up on tmdb')
                slug = letterboxd.slug_from_short_url(uri)
                ids = letterboxd.ids_from_slug(slug)
                tmdb_id = ids[0]
                # imdb_id = ids[1]
                # logger.info(f'Got TMDB id {tmdb_id} and IMDB id {imdb_id}')
                logger.info(f'Got TMDB id {tmdb_id}')

                tmdb_movies = tmdb.search_movie(title=name, year=year)
                if len(tmdb_movies) == 0:
                    logger.info('Searched TMDB, was not able to find.')
                    tmdb_movies = tmdb.search_movie(title=name)

                # seems like a tv show, skip
                if len(tmdb_movies) == 0:
                    pbar.update(1)
                    continue

                tmdb_movie = tmdb_movies[0]

                logger.info(f'Searched TMDB {name} ({year})')
                org_title = name
                org_year = year

                # I think only tmdb_id is needed at this state. Whatever - this is not the bottleneck.
                name = tmdb.translation(tmdb_movie)
                year = tmdb_movie.release_date[:4]
                # combination = Movie(name, year)
                # tmdb_id = tmdb_movie.id
                tmdb.store_movie_to_cache(name, year, org_title, org_year, tmdb_id)

            # if config.tmdb_use_api:
            #     # imdb_id = tmdb.get_imdb_id(tmdb_id)
            #
            #     try:
            #         # try to search the movie the normal way first. compare guid then to avoid using movies.getGuid
            #         # because this function is really, really slow af
            #         # search(): 8 - 12 movies/s <> getGuid(): 2 - 4 movies/s
            #         tmdb_result = movies.search(title=name)
            #         if len(tmdb_result) > 0:
            #             for result in tmdb_result:
            #                 guids = getattr(result, 'guids', [])
            #                 # if any(f"imdb://{imdb_id}" in str(guid.id) for guid in guids):
            #                 if any(f"tmdb://{tmdb_id}" in str(guid.id) for guid in guids):
            #                     logger.info(f'Found {name} ({year}), will add to watchlist')
            #
            #                     movie = result
            #                     missing = util.remove_from_missing_if_needed(missing, was_missing_names)
            #                     break
            #                 else:
            #                     if len(tmdb_result) == 1:  # getGuid makes only sense, when there is only one result
            #                         # result = movies.getGuid(imdb_id)
            #                         movie = movies.getGuid(f'tmdb://{tmdb_id}')
            #                         logger.info(f'Found {name} ({year}) via IMDB ID, will add to watchlist')
            #         else:
            #             # result = movies.getGuid(imdb_id)
            #             movie = movies.getGuid(f'tmdb://{tmdb_id}')
            #             logger.info(f'Found {name} ({year}) via IMDB ID, will add to watchlist')
            #
            #             missing = util.remove_from_missing_if_needed(missing, was_missing_names)
            #     except NotFound:
            #         logger.info(f'Movie {name} ({year}) is missing')
            #         is_present = any(
            #             combination.name == existing.name and combination.year == existing.year for existing in missing)
            #         if not is_present:
            #             logger.debug(f'Movie {name} ({year}) added to missing list')
            #             missing.append(combination)
            if config.tmdb_use_api:
                try:
                    # try to search the movie the normal way first. compare guid then to avoid using movies.getGuid
                    # because this function is really, really slow af
                    # search(): 8 - 12 movies/s <> getGuid(): 2 - 4 movies/s
                    tmdb_result = movies.search(title=name)
                    matches = []

                    if len(tmdb_result) > 0:
                        for result in tmdb_result:
                            guids = getattr(result, 'guids', [])
                            if any(f"tmdb://{tmdb_id}" in str(guid.id) for guid in guids):
                                matches.append(result)

                        if len(matches) == 1:
                            movie = matches[0]
                            logger.info(f'Found {name} ({year}), will use this for rating update')
                            missing = util.remove_from_missing_if_needed(missing, was_missing_names)

                        elif len(matches) > 1:
                            movie = choose_movie(autoselector, combination, matches, logger,
                                                 web_mode=config.web_mode)
                            if movie:
                                logger.info(f'User selected {movie.title} ({movie.year}) for rating update')
                                was_missing_names.append(movie.title)
                                missing = util.remove_from_missing_if_needed(missing, was_missing_names)
                            else:
                                logger.info(f'User skipped selection for {name} ({year})')
                                raise NotFound  # treat as missing if skipped

                        else:
                            # No matching TMDb GUIDs found, fallback to getGuid
                            logger.debug(f'No exact GUID match for {name} ({year}), trying TMDb GUID lookup...')
                            movie = movies.getGuid(f'tmdb://{tmdb_id}')
                            if movie:
                                logger.info(f'Found {name} ({year}) via TMDb ID, will use for rating update')
                                missing = util.remove_from_missing_if_needed(missing, was_missing_names)
                            else:
                                raise NotFound

                    else:
                        # No Plex results at all, fallback to getGuid
                        movie = movies.getGuid(f'tmdb://{tmdb_id}')
                        if movie:
                            logger.info(f'Found {name} ({year}) via TMDb ID, will use for rating update')
                            missing = util.remove_from_missing_if_needed(missing, was_missing_names)
                        else:
                            raise NotFound

                except NotFound:
                    logger.info(f'Movie {name} ({year}) is missing')
                    is_present = any(
                        combination.name == existing.name and combination.year == existing.year for existing in missing
                    )
                    if not is_present:
                        logger.debug(f'Movie {name} ({year}) added to missing list')
                        missing.append(combination)

            else:  # old way
                years = [year, str(int(year) - 1), str(int(year) + 1)]
                result = movies.search(title=name, year=years)

                if len(result) == 1:
                    logger.info(f'Found {name} ({year}), will rate')
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
                cursor.execute(insert_query, (org_title, calculated_rating))
                connection.commit()
                logger.debug('Inserted')

            pbar.update(1)

        IgnoreMovie.store_json(to_ignore)
        MissingMovie.store_json(missing)
        autoselection.AutoSelection.store_json(autoselector)
        logger.info('All ratings imported.')
        progress_callback(f'All ratings imported')


def _read_ratings_csv_():
    file_path = config.ratings_path
    data = []

    with open(file_path, 'r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        next(reader)  # skip header
        for row in reader:
            date, name, year, uri, stars = row
            data.append((name, year, stars, uri))
    return data
