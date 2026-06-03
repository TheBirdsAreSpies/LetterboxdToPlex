import csv
import os


def resolve_existing_path(file_path):
    if not file_path:
        return None

    path = str(file_path)
    candidates = [path]

    if not os.path.isabs(path):
        basename = os.path.basename(path)
        candidates.extend([
            basename,
            os.path.join("data", basename),
            os.path.join("lb", basename),
        ])

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if os.path.exists(candidate):
            return candidate

    return None


def read_general_csv(file_path):
    data = []

    resolved_path = resolve_existing_path(file_path)
    if not resolved_path:
        return data

    with open(resolved_path, 'r', newline='', encoding='utf-8') as file:
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

