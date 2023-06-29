import autoselection
import config
import csv
import datetime
from plexapi.myplex import PlexServer
from plexapi.exceptions import NotFound, BadRequest
from ignoremovie import IgnoreMovie
from mapping import Mapping
from missingmovie import MissingMovie
from movie import Movie
from tqdm import tqdm


def read_watchlist_csv(file_path):
    data = []

    with open(file_path, 'r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        next(reader)  # skip header
        for row in reader:
            date, name, year, uri = row
            data.append((name, year))
    return data

def get_watched_movies_not_rated():
    watched_data = read_general_csv(config.watched_path)
    ratings_data = read_general_csv(config.ratings_path)

    watched_entries = set((row['Name'], row['Year']) for row in watched_data)
    ratings_entries = set((row['Name'], row['Year']) for row in ratings_data)

    entries_not_in_ratings = watched_entries - ratings_entries
    return entries_not_in_ratings

def read_general_csv(file_path):
    data = []

    with open(file_path, 'r', newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            data.append(row)

    return data

def sort_list_ignore_words(lst):
    lst.sort(key=lambda x: ' '.join(word for word in x[0].split() if word.lower() not in config.ignore_words))
    return lst

def sort_playlist_ignore_words(movies):
    sorted_movies = sorted(movies, key=lambda movie: clean_title(movie.title))
    return sorted_movies

def clean_title(title):
    words = title.strip().lower().split()
    cleaned_words = [word for word in words if word not in config.ignore_words]
    cleaned_title = ' '.join(cleaned_words)
    return cleaned_title

def find_movie_by_letterboxd_title(mapping, letterboxd_title):
    for obj in mapping:
        if obj.letterboxd_title == letterboxd_title:
            return obj
    return None

def find_preselection(autoselector, combination, resultset):
    key = None

    for selection in autoselector:
        if selection.combination.name == combination.name:
            key = selection.movie_to_prefer_key
            break

    for movie in resultset:
        if movie.key == key:
            return movie
    return None

def main():
    current_year = datetime.datetime.now().year

    to_ignore = IgnoreMovie.load_json() or []
    mapping = Mapping.load_json() or []
    autoselector = autoselection.AutoSelection.load_json() or []

    plex = PlexServer(config.baseurl, config.token)
    account = plex.myPlexAccount() # only needed when using builtin watchlist
    movies = plex.library.section('Movies')
    tv_shows = plex.library.section('TV Shows')

    data = read_watchlist_csv(config.watchlist_path)
    if config.include_watched_not_rated:
        data += get_watched_movies_not_rated()

    if config.sort_by_title:
        sorted_data = sort_list_ignore_words(data)
    else:
        sorted_data = data

    missing = [] # maybe restore to save new missing entries at the bottom
    to_add = []

    with tqdm(total=len(sorted_data), unit='Movies') as pbar: #ncols=100
        for name, year in sorted_data:
            skip = False
            combination = Movie(name, year)
            pbar.set_description(f'Processing {name} ({year})'.ljust(80, ' '))

            if name == '' or year == '':
                skip = True
            elif int(year) > current_year: # skip movies that have not yet been released
                skip = True
            elif any(combination.name == existing.name and combination.year == existing.year for existing in to_ignore): # movie is in ignore list, maybe remove due to the second check after mapping
                skip = True

            if skip:
                pbar.update(1)
                continue


            mapped = find_movie_by_letterboxd_title(mapping, combination.name)
            if mapped:
                combination = Movie(mapped.plex_title, year)
                name = combination.name

            is_ignored = any(combination.name == existing.name and combination.year == existing.year for existing in to_ignore)
            if is_ignored:
                continue

            years = [year, str(int(year) - 1), str(int(year) + 1)] # include year + 1 because lb is using premiere dates instead of cinema dates
            result = movies.search(title=name, year=years) # use decade to avoid missing movies because of one year diff
            if len(result) == 1:
                to_add.append(result[0])
            elif len(result) > 1:
                counter = 1
                preselection = find_preselection(autoselector, combination, result)

                print(f'\nFound multiple movies for {name} ({year}):')
                if preselection:
                    print(f'Auto selected {preselection.title} ({preselection.year})')
                    to_add.append(preselection)
                else:
                    for movie in result:
                        print(f'{counter}: {movie.title} ({movie.year})')
                        counter += 1

                    selection = int(input('Use:'))
                    if 0 < selection < len(result) + 1:
                        selector = autoselection.AutoSelection(combination, result[selection - 1].key)
                        autoselector.append(selector)
                        autoselection.AutoSelection.store_json(autoselector)
                        to_add.append(result[selection - 1])

            else: # len(result) == 0:
                result = tv_shows.search(title=name) # to ignore tv shows

                if len(result) > 0: # seems like a tv show, ignore
                    is_present = any(combination.name == existing.name and combination.year == existing.year for existing in to_ignore)
                    if not is_present:
                        to_ignore.append(combination)
                else:
                    is_present = any(combination.name == existing.name and combination.year == existing.year for existing in missing)
                    if not is_present:
                        missing.append(combination)

            pbar.update(1)

        if config.use_playlist_as_watchlist:
            try:
                playlist = plex.playlist(config.watchlist_name_to_create)
                playlist.delete()
                print("\nWatchlist deleted.")
            except NotFound:
                print("\nPlaylist not existing yet. No worries, nothing to do.")

            if config.ignore_movies_in_existing_watchlist:
                try:
                    existing_playlist = plex.playlist(config.existing_watchlist_name)

                    to_add_cleaned = []
                    for m in to_add:
                        is_in_playlist = any(movie.title == m.title and movie.year == m.year for movie in existing_playlist.items())
                        if not is_in_playlist:
                            to_add_cleaned.append(m)

                    to_add = to_add_cleaned
                except NotFound:
                    print("\nExisting watchlist not found!")

            if config.sort_by_title:
                to_add = sort_playlist_ignore_words(to_add)

            plex.createPlaylist(title='Letterboxd Watchlist', items=to_add)

        if config.use_builtin_watchlist:
            for movie in to_add:
                try:
                    account.addToWatchlist(movie)
                except BadRequest:
                    print("\nAlready on watchlist - ignore.")


        IgnoreMovie.store_json(to_ignore)
        MissingMovie.store_json(missing)
        autoselection.AutoSelection.store_json(autoselector)

    print("Done")

if __name__ == "__main__":
    main()