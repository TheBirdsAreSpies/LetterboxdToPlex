import logging

import config
import letterboxd
import tmdb
from selector import choose_movie

from plexapi.exceptions import NotFound


def lookup_tmdb(name, year, uri, logger: logging.Logger):
    """
    Resolves the TMDB id of a Letterboxd entry and the title/year to search Plex with.

    Returns: (tmdb_id, title, year) tuple, title and year are None if the movie was not found on TMDB
    """
    logger.debug('Trying to look it up on tmdb')
    slug = letterboxd.slug_from_short_url(uri)
    ids = letterboxd.ids_from_slug(slug)
    tmdb_id = ids[0]
    logger.info(f'Got TMDB id {tmdb_id}')

    tmdb_movies = tmdb.search_movie(title=name, year=year)
    if len(tmdb_movies) == 0:
        logger.info('Searched TMDB, was not able to find.')
        tmdb_movies = tmdb.search_movie(title=name)
        if len(tmdb_movies) == 0:
            return tmdb_id, None, None

    tmdb_movie = tmdb_movies[0]
    logger.info(f'Searched TMDB {name} ({year})')

    # I think only tmdb_id is needed at this state. Whatever - this is not the bottleneck.
    translated_name = tmdb.translation(tmdb_movie)
    tmdb_year = tmdb_movie.release_date[:4]

    if tmdb_year != '':  # could be empty if there is no rls-date on tmdb
        tmdb.store_movie_to_cache(translated_name, tmdb_year, name, year, tmdb_id)

    return tmdb_id, translated_name, tmdb_year


def find_by_tmdb_id(movies, name, tmdb_id, autoselector, combination, logger: logging.Logger):
    """Returns the Plex movie matching the TMDB id, or None if it is not in the library or the selection was skipped."""
    # try to search the movie the normal way first. compare guid then to avoid using movies.getGuid
    # because this function is really, really slow af
    # search(): 8 - 12 movies/s <> getGuid(): 2 - 4 movies/s
    results = movies.search(title=name)
    matches = [
        result for result in results
        if any(f"tmdb://{tmdb_id}" in str(guid.id) for guid in getattr(result, 'guids', []))
    ]

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        logger.info(f'Found multiple possible matches for {name}')
        return choose_movie(autoselector, combination, matches, logger, web_mode=config.web_mode)

    # No matching TMDB GUIDs found, fallback to slower getGuid()
    logger.debug(f'No exact GUID match found for {name}, trying TMDB GUID lookup...')
    try:
        return movies.getGuid(f'tmdb://{tmdb_id}')
    except NotFound:
        return None


def find_by_title(movies, name, year, autoselector, combination, logger: logging.Logger):
    """Returns the Plex movie matching title and year, or None if it is not in the library or the selection was skipped."""
    # include year + 1 because lb is using premiere dates instead of cinema dates
    years = [str(year), str(int(year) - 1), str(int(year) + 1)]
    results = movies.search(title=name, year=years)

    if len(results) == 1:
        return results[0]

    if len(results) > 1:
        logger.info(f'Found multiple movies for {name} ({year})')
        return choose_movie(autoselector, combination, results, logger, web_mode=config.web_mode)

    return None
