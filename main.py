import argparse
import config
import letterboxd
import owned
import rating
import tmdb
import watchlist
import zipfile
import logging

from session import Session
from plexapi.myplex import PlexServer


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.FileHandler('ltp.log', encoding='utf-8')]
    )

    plex = PlexServer(config.baseurl, config.token)
    movies = plex.library.section('Movies')

    parser = argparse.ArgumentParser(prog='LetterboxdToPlex',
                                     description='Tool to export movie information from Plex to Letterboxd and vice versa')
    parser.add_argument('-r', '--rating', action='store_true', help='exports Letterboxd ratings to Plex movies')
    parser.add_argument('-o', '--owned', type=int, nargs='?', const=-1,
                        help='creates a csv file to import to a Letterboxd list. ' +
                             'Used to get the \'owned\' filter. If number is passed after, only that amount of recent movies ' +
                             'will get processed')
    parser.add_argument('-w', '--watchlist', action='store_true',
                        help='exports movies from Letterboxd watchlist to Plex')
    args = parser.parse_args()

    logger = logging.getLogger('')
    logger.setLevel(level=logging.INFO)

    if config.tmdb_use_api:
        # tmdb.drop_table()
        tmdb.reorganize_indexes()
        tmdb.create_table()
        tmdb.invalidate_cache()
        letterboxd.create_table()

    if args.watchlist or (args.owned is None and not args.rating):
        if config.use_api:
            zipfile_name = 'letterboxd_export.zip'
            session = Session(config.api_username, config.api_password, config.api_use_2fa_code)
            session.download_export_data(zipfile_name)

            with zipfile.ZipFile(zipfile_name, 'r') as zip_ref:
                zip_ref.extractall('.')

        logger.name = 'WATCHLIST'
        watchlist.watchlist(plex, movies, logger)
    if args.owned is not None:
        logger.name = 'OWNED'
        owned.create_csv(movies, args.owned, logger)
    if args.rating:
        logger.name = 'RATING'
        rating.rating(plex, movies, logger)

    print("Done")


if __name__ == "__main__":
    main()
