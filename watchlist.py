import logging
import config
import datetime
import autoselection
import csv
import matching
import tmdb
import util

from plexapi.exceptions import NotFound, BadRequest
from missingmovie import MissingMovie
from ignoremovie import IgnoreMovie
from mapping import Mapping
from movie import Movie
from tqdm import tqdm

# release dates of missing movies are refreshed on every sync, but at most once within this time
RELEASE_DATE_MAX_AGE_HOURS = 24


def _refresh_release_date_for_missing(tmdb_id):
    try:
        return tmdb.get_configured_release_date_for_movie(tmdb_id, refresh=True,
                                                          max_age_hours=RELEASE_DATE_MAX_AGE_HOURS)
    except Exception:
        return None


def _mark_missing(missing, combination, tmdb_id, logger: logging.Logger):
    existing = util.find_missing(missing, combination)
    if existing is None:
        logger.debug(f'Movie {combination.name} ({combination.year}) added to missing list')
        existing = combination
        missing.append(combination)

    if tmdb_id is not None:
        logger.debug(f'Refreshing release_date for movie {existing.name} ({existing.year})')
        existing.release_date = _refresh_release_date_for_missing(tmdb_id)


def watchlist(plex, movies, logger: logging.Logger, progress_callback=None):
    current_year = datetime.datetime.now().year
    to_ignore = IgnoreMovie.load_json() or []
    mapping = Mapping.load_json() or []
    autoselector = autoselection.AutoSelection.load_json() or []

    publish_progress = util.progress_publisher(logger, progress_callback)
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
    library = matching.LibraryIndex(movies, logger)

    with tqdm(total=len(sorted_data), unit='Movies') as pbar:
        for name, year, uri in sorted_data:
            skip = False
            combination = Movie(name, year)
            pbar.set_description(f'Processing {name} ({year})'.ljust(80, ' '))
            publish_progress(f'Processing {name} ({year})')

            was_missing_names = []

            if name == '' or year == '':
                logger.info(f'Skipping: Name ({name}) or year ({year}) is empty')
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

            lb_name = name
            lb_year = year
            tmdb_id = None
            if config.tmdb_use_api:
                tmdb_id = matching.tmdb_id_from_uri(uri, logger)

            manually_mapped = util.find_movie_by_letterboxd_title(mapping, combination)

            was_missing_names.append(combination.name)
            if manually_mapped:
                if manually_mapped.year > -1:
                    year = manually_mapped.year
                logger.info(f'Movie {combination.name} ({combination.year})'
                            f' is mapped to {manually_mapped.plex_title} ({year})')
                combination = Movie(manually_mapped.plex_title, year)
                name = combination.name

            is_ignored = any(combination.name == existing.name
                             and combination.year == existing.year
                             for existing in to_ignore)
            if is_ignored:
                logger.info(f'Skipping: Movie {name} ({year}) should be ignored')
                pbar.update(1)
                continue

            # add to list, will remove later if found
            was_missing_names.append(name)

            if config.tmdb_use_api:
                selected = matching.find_by_tmdb_id(library, movies, tmdb_id, autoselector, combination, logger)
            else:
                selected = matching.find_by_title(movies, name, year, autoselector, combination, logger)

            if selected:
                logger.info(f'Found {selected.title} ({selected.year}), will add to watchlist')
                to_add.append(selected)
                was_missing_names.append(selected.title)
                missing = util.remove_from_missing_if_needed(missing, was_missing_names)
                pbar.update(1)
                continue

            if config.tmdb_use_api:
                # tmdb data is only needed for the missing list, so it is resolved for missing movies only
                tmdb_name, tmdb_year = matching.lookup_tmdb(lb_name, lb_year, tmdb_id, logger)
                if tmdb_name is not None and tmdb_year == '':  # could happen if there is no rls-date on tmdb
                    pbar.update(1)
                    continue

            logger.info(f'Movie {name} ({year}) is missing')
            _mark_missing(missing, combination, tmdb_id, logger)

            pbar.update(1)

    if config.use_playlist_as_watchlist:
        try:
            playlist = plex.playlist(config.watchlist_name_to_create)
            playlist.delete()
            pbar.write("\nWatchlist deleted.")
            publish_progress("Watchlist deleted.")
        except NotFound:
            pbar.write("\nPlaylist not existing yet. No worries, nothing to do.")
            publish_progress("Playlist not existing yet. No worries, nothing to do.")


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
                if progress_callback:
                    progress_callback("Existing watchlist not found!")

        if config.sort_by_title:
            to_add = __sort_playlist_ignore_words__(to_add)

        if len(to_add) > 0:
            plex.createPlaylist(title=config.watchlist_name_to_create, items=to_add)
            logger.info('Watchlist created')
        else:
            logger.info('Nothing to add.')

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

    publish_progress("Synchronized Watchlist")


def __read_watchlist_csv__(file_path):
    data = []

    resolved_path = util.resolve_existing_path(file_path)
    if not resolved_path:
        return data

    with open(resolved_path, 'r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        next(reader)  # skip header
        for row in reader:
            date, name, year, uri = row
            data.append((name, year, uri))
    return data


def __get_watched_movies_not_rated__():
    watched_data = util.read_general_csv(config.watched_path)
    ratings_data = util.read_general_csv(config.ratings_path)

    watched_entries = set((row['Name'], row['Year'], row['Letterboxd URI']) for row in watched_data)
    ratings_entries = set((row['Name'], row['Year'], row['Letterboxd URI']) for row in ratings_data)

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
