import autoselection
import util
import threading

selection_requests = {}  # active pending selections for web (keyed by movie name)
selection_events = {}    # threading.Event to block until web selection arrives
selection_results = {}   # result chosen via web


def choose_movie(autoselector, combination, results, logger, web_mode=False):
    preselection = util.find_preselection(autoselector, combination, results)
    if preselection:
        logger.info(f'Auto selected {preselection.title} ({preselection.year})')
        return preselection

    # If in web mode -> wait for user to pick in browser
    if web_mode:
        selection_requests[combination.name] = {
            "combination": combination,
            "options": [
                {
                    "key": movie.key,
                    "title": movie.title,
                    "year": movie.year,
                    "edition": movie.editionTitle,
                }
                for movie in results
            ]
        }
        ev = threading.Event()
        selection_events[combination.name] = ev
        ev.wait()  # block until user picks
        chosen_key = selection_results.pop(combination.name, None)

        if not chosen_key:  # most likely pressed "Skip" button
            return None

        selection_requests.pop(combination.name, None)
        selection_events.pop(combination.name, None)

        chosen_movie = next((m for m in results if m.key == chosen_key), None)
        if chosen_movie:
            selector = autoselection.AutoSelection(combination, chosen_movie.key)
            autoselector.append(selector)
            autoselection.AutoSelection.store_json(autoselector)
            logger.info(f'User (web) selected {chosen_movie.title} ({chosen_movie.year})')
        return chosen_movie

    # Otherwise -> CLI prompt
    print(f'\nFound multiple movies for {combination.name} ({combination.year}):')
    for i, movie in enumerate(results, 1):
        edition = f", {movie.editionTitle}" if movie.editionTitle else ""
        print(f'{i}: {movie.title} ({movie.year}{edition})')

    selection = int(input('Select movie: '))
    if 1 <= selection <= len(results):
        chosen = results[selection - 1]
        logger.info(f'Console selected {chosen.title} ({chosen.year})')
        selector = autoselection.AutoSelection(combination, chosen.key)
        autoselector.append(selector)
        autoselection.AutoSelection.store_json(autoselector)
        return chosen
    else:
        logger.warning("Invalid selection — skipping.")
        return None
