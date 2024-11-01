import logging

import config
import datetime
import autoselection
import csv
import util

from plexapi.exceptions import NotFound, BadRequest
from missingmovie import MissingMovie
from ignoremovie import IgnoreMovie
from mapping import Mapping
from movie import Movie
from tqdm import tqdm


def watchlist(plex, movies, logger: logging.Logger):
    current_year = datetime.datetime.now().year
    to_ignore = IgnoreMovie.load_json() or []
    mapping = Mapping.load_json() or []
    autoselector = autoselection.AutoSelection.load_json() or []
    logger.info("Started importing watchlist")

    data = __read_watchlist_csv__(config.watchlist_path)
    if config.include_watched_not_rated:
        data += __get_watched_movies_not_rated__()

    if config.sort_by_title:
        sorted_data = __sort_list_ignore_words__(data)
    else:
        sorted_data = data

    missing = MissingMovie.load_json() or []
    to_add = []

    with tqdm(total=len(sorted_data), unit='Movies') as pbar:
        for name, year in sorted_data:
            skip = False
            combination = Movie(name, year)
            pbar.set_description(f'Processing {name} ({year})'.ljust(80, ' '))
            logger.debug(f'Processing {name} ({year})')
            was_missing_names = []

            if name == '' or year == '':
                logger.debug(f'Skipping: Name ({name}) or year ({year}) is empty')
                skip = True
            elif int(year) > current_year:  # skip movies that yet have not been released
                logger.info(f'Skipping: Movie {name} is not released yet ({year})')
                skip = True
            elif any(combination.name == existing.name and combination.year == existing.year for existing in
                     to_ignore):  # movie is in ignore list, maybe remove due to the second check after mapping
                logger.info(f'Skipping: Movie {name} ({year}) should be ignored')
                skip = True

            if skip:
                pbar.update(1)
                continue

            mapped = util.find_movie_by_letterboxd_title(mapping, combination)
            was_missing_names.append(combination.name)
            if mapped:
                if mapped.year > -1:
                    year = mapped.year
                logger.info(f'Movie {combination.name} ({combination.year}) is mapped to {mapped.plex_title} ({year})')
                combination = Movie(mapped.plex_title, year)
                name = combination.name

            is_ignored = any(
                combination.name == existing.name and combination.year == existing.year for existing in to_ignore)
            if is_ignored:
                logger.info(f'Skipping: Movie {name} ({year}) should be ignored')
                pbar.update(1)
                continue

            # include year + 1 because lb is using premiere dates instead of cinema dates
            years = [year, str(int(year) - 1), str(int(year) + 1)]
            result = movies.search(title=name, year=years)
            was_missing_names.append(name)

            if len(result) == 1:
                logger.debug(f'Found {name} ({year}), will add to watchlist')
                to_add.append(result[0])
                missing = util.remove_from_missing_if_needed(missing, was_missing_names)

            elif len(result) > 1:
                preselection = util.find_preselection(autoselector, combination, result)

                logger.info(f'Found multiple movies for {name} ({year})')
                if preselection:
                    logger.info(f'Auto selected {preselection.title} ({preselection.year})')
                    to_add.append(preselection)
                    was_missing_names.append(preselection.title)
                    missing = util.remove_from_missing_if_needed(missing, was_missing_names)
                else:
                    counter = 1
                    print(f'\nFound multiple movies for {name} ({year}):')

                    for movie in result:
                        if movie.editionTitle is None:
                            logger.debug(f'{counter}: {movie.title} ({movie.year})')
                            print(f'{counter}: {movie.title} ({movie.year})')
                        else:
                            logger.debug(f'{counter}: {movie.title} ({movie.year}, {movie.editionTitle})')
                            print(f'{counter}: {movie.title} ({movie.year}, {movie.editionTitle})')

                        counter += 1

                    selection = int(input('Use:'))
                    if 0 < selection < len(result) + 1:
                        res = result[selection - 1]
                        logger.debug(f'WATCHLIST: Selected {counter}: {res.title}')
                        selector = autoselection.AutoSelection(combination, res.key)
                        autoselector.append(selector)
                        autoselection.AutoSelection.store_json(autoselector)
                        to_add.append(res)
                        was_missing_names.append(res.title)
                        missing = util.remove_from_missing_if_needed(missing, was_missing_names)

            else:  # len(result) == 0:
                logger.info(f'Movie {name} ({year}) is missing')
                is_present = any(
                    combination.name == existing.name and combination.year == existing.year for existing in missing)
                if not is_present:
                    logger.debug(f'Movie {name} ({year}) added to missing list')
                    missing.append(combination)

            pbar.update(1)

    if config.use_playlist_as_watchlist:
        try:
            playlist = plex.playlist(config.watchlist_name_to_create)
            playlist.delete()
            logger.info('Watchlist deleted')
            pbar.write("\nWatchlist deleted.")
        except NotFound:
            logger.info('Playlist not existing yet. No worries, nothing to do.')
            pbar.write("\nPlaylist not existing yet. No worries, nothing to do.")

        if config.ignore_movies_in_existing_watchlist:
            try:
                existing_playlist = plex.playlist(config.existing_watchlist_name)

                to_add_cleaned = []
                for m in to_add:
                    is_in_playlist = any(
                        movie.title == m.title and movie.year == m.year for movie in existing_playlist.items())
                    if not is_in_playlist:
                        to_add_cleaned.append(m)

                to_add = to_add_cleaned
            except NotFound:
                logger.warning('Existing watchlist not found!')
                pbar.write("\nExisting watchlist not found!")

        if config.sort_by_title:
            to_add = __sort_playlist_ignore_words__(to_add)

        plex.createPlaylist(title='Letterboxd Watchlist', items=to_add)
        logger.info('Watchlist created')

    if config.use_builtin_watchlist:
        account = plex.myPlexAccount()
        for movie in to_add:
            try:
                account.addToWatchlist(movie)
                logger.debug(f'Internal Watchlist added {movie.title} ({movie.year})')
            except BadRequest:
                logger.info('Internal Watchlist already on watchlist - ignore.')

    IgnoreMovie.store_json(to_ignore)
    MissingMovie.store_json(missing)
    autoselection.AutoSelection.store_json(autoselector)


def __read_watchlist_csv__(file_path):
    data = []

    with open(file_path, 'r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        next(reader)  # skip header
        for row in reader:
            date, name, year, uri = row
            data.append((name, year))
    return data


def __get_watched_movies_not_rated__():
    watched_data = util.read_general_csv(config.watched_path)
    ratings_data = util.read_general_csv(config.ratings_path)

    watched_entries = set((row['Name'], row['Year']) for row in watched_data)
    ratings_entries = set((row['Name'], row['Year']) for row in ratings_data)

    entries_not_in_ratings = watched_entries - ratings_entries
    return entries_not_in_ratings


def __sort_list_ignore_words__(lst):
    lst.sort(key=lambda x: ' '.join(word for word in x[0].split() if word.lower() not in config.ignore_words))
    return lst


def __sort_playlist_ignore_words__(movies):
    sorted_movies = sorted(movies, key=lambda movie: __clean_title__(movie.title))
    return sorted_movies


def __clean_title__(title):
    words = title.strip().lower().split()
    cleaned_words = [word for word in words if word not in config.ignore_words]
    cleaned_title = ' '.join(cleaned_words)
    return cleaned_title
