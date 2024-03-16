import plexapi.video
import autoselection
import config
import csv
import logging
import util

from mapping import Mapping
from movie import Movie
from ignoremovie import IgnoreMovie
from missingmovie import MissingMovie
from tqdm import tqdm


def rating(plex, movies):
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    # https://betterstack.com/community/guides/logging/best-python-logging-libraries/

    tv_shows = plex.library.section('TV Shows')

    to_ignore = IgnoreMovie.load_json() or []
    missing = MissingMovie.load_json() or []
    autoselector = autoselection.AutoSelection.load_json() or []
    mapping = Mapping.load_json() or []

    data = _read_ratings_csv_()

    with tqdm(total=len(data), unit='Movies') as pbar:
        for name, year, stars in data:
            pbar.set_description(f'Processing {name} ({year})'.ljust(80, ' '))
            was_missing_names = []

            years = [year, str(int(year) - 1), str(int(year) + 1)]
            combination = Movie(name, year)

            if any(combination.name == existing.name and combination.year == existing.year for existing in
                   to_ignore):  # movie is in ignore list, maybe remove due to the second check after mapping
                pbar.update(1)
                continue

            mapped = util.find_movie_by_letterboxd_title(mapping, combination.name)
            if mapped:
                if mapped.year > -1:
                    year = mapped.year
                combination = Movie(mapped.plex_title, year)
                name = combination.name

            result = movies.search(title=name, year=years)

            if len(result) == 1:
                movie: plexapi.video.Movie = result[0]
                missing = util.remove_from_missing_if_needed(missing, was_missing_names)

            elif len(result) > 1:
                counter = 1
                preselection = util.find_preselection(autoselector, combination, result)

                print(f'\nFound multiple movies for {name} ({year}):')
                if preselection:
                    print(f'Auto selected {preselection.title} ({preselection.year})')
                    movie = preselection
                    was_missing_names.append(preselection.title)
                    missing = util.remove_from_missing_if_needed(missing, was_missing_names)
                else:
                    for movie in result:
                        print(f'{counter}: {movie.title} ({movie.year})')
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
                result = tv_shows.search(title=name)  # to ignore tv shows

                if len(result) > 0:  # seems like a tv show, ignore
                    is_present = any(
                        combination.name == existing.name and combination.year == existing.year for existing in
                        to_ignore)
                    if not is_present:
                        to_ignore.append(combination)
                else:
                    is_present = any(
                        combination.name == existing.name and combination.year == existing.year for existing in missing)
                    if not is_present:
                        missing.append(combination)

                pbar.update(1)
                continue

            calculated_rating = float(stars) * 2
            if movie.userRating != calculated_rating:
                movie.rate(calculated_rating)

            pbar.update(1)

        IgnoreMovie.store_json(to_ignore)
        MissingMovie.store_json(missing)
        autoselection.AutoSelection.store_json(autoselector)
        print('All ratings imported.')


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
