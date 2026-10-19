import logging
import time

import config
import letterboxd
import tmdb
from selector import choose_movie

from concurrent.futures import ThreadPoolExecutor
from plexapi.exceptions import NotFound


class LibraryIndex:
    """
    Loads the whole Plex library once and looks movies up by TMDB id in memory.

    A search per movie takes 0.2 - 0.7 s (getGuid even ~2 s), loading the library once takes a few seconds.
    """
    PAGE_SIZE = 1000
    PARALLEL_PAGES = 4
    MODERN_AGENT = 'tv.plex.agents.movie'
    # only guids, title, year and edition are needed, skipping the rest makes the response much smaller
    EXCLUDE_ELEMENTS = 'Media,Genre,Country,Director,Writer,Role,Producer,Collection,Label,Field,Image,Rating,UltraBlurColors'

    def __init__(self, movies, logger: logging.Logger):
        self._movies = movies
        self._logger = logger
        self._by_tmdb_id = None

    @property
    def is_complete(self):
        # items of legacy agents have no tmdb guids, the index can only be trusted for the modern agent
        return getattr(self._movies, 'agent', None) == self.MODERN_AGENT

    def _fetch_page(self, start):
        key = (f'/library/sections/{self._movies.key}/all?type=1&includeGuids=1'
               f'&excludeElements={self.EXCLUDE_ELEMENTS}&excludeFields=summary,tagline')
        return self._movies._server.fetchItems(key, container_start=start, container_size=self.PAGE_SIZE,
                                               maxresults=self.PAGE_SIZE)

    def _load(self):
        if self._by_tmdb_id is not None:
            return self._by_tmdb_id

        started = time.time()
        with ThreadPoolExecutor(self.PARALLEL_PAGES) as executor:
            pages = list(executor.map(self._fetch_page, range(0, self._movies.totalSize, self.PAGE_SIZE)))

        self._by_tmdb_id = {}
        count = 0
        for page in pages:
            for movie in page:
                count += 1
                for guid in getattr(movie, 'guids', []):
                    if str(guid.id).startswith('tmdb://'):
                        self._by_tmdb_id.setdefault(str(guid.id), []).append(movie)

        self._logger.info(f'Loaded {count} movies from Plex in {time.time() - started:.1f} s')
        return self._by_tmdb_id

    def find(self, tmdb_id):
        return self._load().get(f'tmdb://{tmdb_id}', [])


def is_valid_tmdb_id(tmdb_id):
    return tmdb_id is not None and str(tmdb_id).strip() not in {'', '-1', 'None', 'null'}


def tmdb_id_from_uri(uri, logger: logging.Logger):
    slug = letterboxd.slug_from_short_url(uri)
    tmdb_id = letterboxd.ids_from_slug(slug)[0]
    logger.info(f'Got TMDB id {tmdb_id}')
    return tmdb_id


def lookup_tmdb(name, year, tmdb_id, logger: logging.Logger):
    """
    Resolves the translated title and year of a Letterboxd entry on TMDB and caches them for the missing list.

    Returns: (title, year) tuple, both are None if the movie was not found on TMDB
    """
    logger.debug('Trying to look it up on tmdb')
    tmdb_movies = tmdb.search_movie(title=name, year=year)
    if len(tmdb_movies) == 0:
        logger.info('Searched TMDB, was not able to find.')
        tmdb_movies = tmdb.search_movie(title=name)
        if len(tmdb_movies) == 0:
            return None, None

    tmdb_movie = tmdb_movies[0]
    logger.info(f'Searched TMDB {name} ({year})')

    translated_name = tmdb.translation(tmdb_movie)
    tmdb_year = tmdb_movie.release_date[:4]

    if tmdb_year != '':  # could be empty if there is no rls-date on tmdb
        tmdb.store_movie_to_cache(translated_name, tmdb_year, name, year, tmdb_id)

    return translated_name, tmdb_year


def find_by_tmdb_id(library: LibraryIndex, movies, tmdb_id, autoselector, combination, logger: logging.Logger):
    """Returns the Plex movie matching the TMDB id, or None if it is not in the library or the selection was skipped."""
    if not is_valid_tmdb_id(tmdb_id):
        return None

    matches = library.find(tmdb_id)

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        logger.info(f'Found multiple possible matches for {combination.name}')
        return choose_movie(autoselector, combination, matches, logger, web_mode=config.web_mode)

    if library.is_complete:
        return None

    # legacy agents do not provide tmdb guids, fallback to the slow getGuid()
    logger.debug(f'TMDB id {tmdb_id} not in library index, trying TMDB GUID lookup...')
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
