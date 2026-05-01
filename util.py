import csv


def read_general_csv(file_path):
    data = []

    with open(file_path, 'r', newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            data.append(row)

    return data


def find_preselection(autoselector, combination, resultset):
    key = None

    for selection in autoselector:
        if selection.combination.name == combination.name \
                and selection.combination.year == combination.year:
            key = selection.movie_to_prefer_key
            break

    for movie in resultset:
        if movie.key == key:
            return movie
    return None


def find_movie_by_letterboxd_title(mapping, combination):
    for obj in mapping:
        if obj.letterboxd_title == combination.name:  # and (obj.year == -1 or str(obj.year) == combination.year):
            return obj
    return None


def _normalize_title(value):
    if value is None:
        return ""
    return str(value).strip().lower()


def remove_from_missing_if_needed(missing, names):
    names_set = {_normalize_title(name) for name in names if _normalize_title(name)}
    if not names_set:
        return missing

    return [movie for movie in missing if _normalize_title(movie.name) not in names_set]

