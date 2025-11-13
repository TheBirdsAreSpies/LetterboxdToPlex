import csv
import logging
import io

from tqdm import tqdm


def create_csv(movies, max_results, logger: logging.Logger, filename="owned.csv"):
    to_export = []

    if max_results <= 0:
        logger.info('No max results set.')
        to_loop = movies.search()
    else:
        logger.info(f'Max results set to {max_results}')
        to_loop = movies.recentlyAdded(maxresults=max_results)

    with tqdm(total=len(to_loop), unit='Movies') as pbar:
        for movie in to_loop:
            pbar.set_description(f'Processing {movie.title} ({movie.year})'.ljust(80, ' '))
            for guid in movie.guids:
                if guid.id.startswith('imdb'):
                    comb = [movie.title, guid.id[len("imdb://"):]]
                    to_export.append(comb)
                    logger.info(f'Appended {movie.title}')
                    break
            pbar.update(1)

    # Save CSV to disk
    with open(filename, mode="w", newline="", encoding="utf-8") as csv_file:
        csv_writer = csv.writer(csv_file, delimiter=',')
        csv_writer.writerow(["Title", "imdbID"])
        for m in to_export:
            csv_writer.writerow(m)
    logger.info(f"CSV saved to {filename}")

    # Also return CSV content as string for download
    output = io.StringIO()
    csv_writer = csv.writer(output, delimiter=',')
    csv_writer.writerow(["Title", "imdbID"])
    for m in to_export:
        csv_writer.writerow(m)
    output.seek(0)
    return output.getvalue()

