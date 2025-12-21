import argparse
import os
import json
import logging
import queue
import threading
import time

from flask import Flask, jsonify, request, Response, render_template
from enum import Enum

import csv
import config
import letterboxd
import owned
import rating
import re
import tmdb
import watchlist
import zipfile
import selector

from session import Session
from plexapi.myplex import PlexServer

app = Flask(__name__)
progress_queues = {}

plex = None
movies = None


def load_json(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=3, ensure_ascii=False)

def lb_export():
    zipfile_name = 'letterboxd_export.zip'
    skip_download = False

    if os.path.exists(zipfile_name):
        mtime = os.path.getmtime(zipfile_name)
        age_seconds = time.time() - mtime
        if age_seconds < 5 * 60:
            skip_download = True

    if not skip_download:
        session = Session(config.api_username, config.api_password, config.api_use_2fa_code)
        session.download_export_data(zipfile_name)

    if os.path.exists(zipfile_name):
        with zipfile.ZipFile(zipfile_name, 'r') as zip_ref:
            zip_ref.extractall('.')

def run_watchlist(logger, progress_callback=None):
    lb_export()

    logger.name = 'WATCHLIST'
    watchlist.watchlist(plex, movies, logger, progress_callback)
    return "Imported watchlist"

def run_owned(logger, amount=200):
    logger.name = 'OWNED'
    return owned.create_csv(movies, amount, logger)

def run_rating(logger, progress_callback=None):
    lb_export()

    logger.name = 'RATING'
    rating.rating(plex, movies, logger, progress_callback)
    return "Updated ratings"

@app.route("/")
def index():
    missing = load_json(config.missing_path)
    return render_template("index.html", missing=missing)

@app.route("/ignore", methods=["POST"])
def ignore():
    data = request.get_json()
    name = data.get("name")

    missing = load_json(config.missing_path)
    ignore_list = load_json(config.ignore_path)

    for item in missing:
        if item["name"] == name:
            ignore_list.append(item)
            missing.remove(item)
            break

    save_json(config.missing_path, missing)
    save_json(config.ignore_path, ignore_list)
    return jsonify(success=True)

def load_csv_names(path):
    names = set()
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("Name", "").strip().lower()
            if name:
                names.add(name)
    return names


@app.route("/action/<name>", methods=["POST"])
def action(name):
    logger = logging.getLogger('')
    logger.setLevel(logging.INFO)

    if name not in [
        "watchlist",
        "owned",
        "rating",
        "cleanup_missing",
        "strip_missing_years"
    ]:
        return jsonify(success=False, message=f"Unknown action '{name}'")

    if name in ["watchlist", "rating"]:
        # threaded actions
        if name in progress_queues and progress_queues[name] is not None:
            return jsonify(success=False, message=f"{name.capitalize()} task already running")

        q = queue.Queue()
        progress_queues[name] = q

        def progress_callback(msg):
            q.put(msg)

        def run_task():
            try:
                if name == "watchlist":
                    run_watchlist(logger, progress_callback)
                elif name == "rating":
                    run_rating(logger, progress_callback)
            finally:
                q.put(None)
                progress_queues[name] = None  # mark done

        threading.Thread(target=run_task, daemon=True).start()
        return jsonify(success=True, message=f"{name.capitalize()} task started")

    elif name == "owned":
        csv_data = run_owned(logger)
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=owned.csv"}
        )

    elif name == "cleanup_missing":
        with open(config.missing_path, "r", encoding="utf-8") as f:
            missing = json.load(f)

        known_names = set()
        known_names |= load_csv_names(config.watchlist_path)
        known_names |= load_csv_names(config.watched_path)
        known_names |= load_csv_names(config.ratings_path)

        original_count = len(missing)

        cleaned = [
            m for m in missing
            if m.get("name", "").strip().lower() in known_names
        ]

        with open(config.missing_path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=2)

        return jsonify(
            success=True,
            message=f"Removed {original_count - len(cleaned)} entries from missing list"
        )

    elif name == "strip_missing_years":
        with open(config.missing_path, "r", encoding="utf-8") as f:
            missing = json.load(f)

        changed = 0

        for m in missing:
            if m["release_date"] is not None:
                m["release_date"] = None
                changed += 1

        with open(config.missing_path, "w", encoding="utf-8") as f:
            json.dump(missing, f, indent=2)

        return jsonify(
            success=True,
            message=f"Cleaned years from {changed} missing entries"
        )

@app.route("/stream/watchlist")
def stream_watchlist():
    q = progress_queues.get('watchlist')
    if not q:
        return "No watchlist running", 404

    def generate():
        while True:
            msg = q.get()
            if msg is None:
                break
            yield f"data: {msg}\n\n"

    return Response(generate(), mimetype='text/event-stream')

@app.route("/config", methods=["GET"])
def config_page():
    # return HTML page
    return render_template("config.html")

@app.route("/config/data")
def config_data():
    if os.path.exists(config.config_path):
        with open(config.config_path, encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = {}
        for key in dir(config):
            if key.startswith("_") or not key.islower():
                continue
            value = getattr(config, key)

            if isinstance(value, type(config)):
                continue

            # convert enums to string
            if isinstance(value, Enum):
                value = str(value)

            cfg[key] = value
    return jsonify(cfg)

@app.route("/config/save", methods=["POST"])
def config_save():
    global plex, movies
    try:
        cfg = request.get_json()

        with open(config.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)

        for key, value in cfg.items():
            setattr(config, key, value)

        connected = False
        try:
            if config.tmdb_use_api:
                tmdb.create_table()
                tmdb.reorganize_indexes()
                tmdb.invalidate_cache()
                letterboxd.create_table()

            plex = PlexServer(config.baseurl, config.token)
            movies = plex.library.section('Movies')
            connected = True
        except Exception as e:
            plex = None
            movies = None
            return jsonify({
                "success": True,
                "plex_connected": False,
                "message": f"Config saved, but failed to connect to Plex: {str(e)}"
            })

        return jsonify({
            "success": True,
            "plex_connected": connected,
            "message": "Config saved and connected to Plex successfully"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        })

@app.route("/autoselections")
def get_autoselections():
    # return all pending selections as JSON
    l = []
    for sel in selector.selection_requests.values():
        combination = sel["combination"]
        combination_dict = {
            "name": combination.name,
            "year": combination.year
        }
        l.append({
            "combination": combination_dict,
            "options": sel["options"]
        })
    return jsonify(l)

@app.route("/autoselections/choose", methods=["POST"])
def choose_autoselection():
    try:
        data = request.get_json()
        combo_name = data.get("name")
        combo_year = data.get("year")
        selected_key = data.get("selected_key")

        key_to_set_event = None

        for sel_id, sel in list(selector.selection_requests.items()):
            combo = sel["combination"]
            if combo.name == combo_name and combo.year == combo_year:
                from autoselection import AutoSelection
                autoselector = AutoSelection.load_json() or []
                autoselector.append(AutoSelection(combo, selected_key))
                AutoSelection.store_json(autoselector)

                key_to_set_event = combo.name

                del selector.selection_requests[sel_id]
                break

        # signal waiting thread
        if key_to_set_event and key_to_set_event in selector.selection_events:
            selector.selection_results[key_to_set_event] = selected_key
            selector.selection_events[key_to_set_event].set()

        return jsonify(success=True, message=f"Selected {combo_name} ({combo_year})")

    except Exception as e:
        return jsonify(success=False, message=str(e))

@app.route("/autoselections/skip", methods=["POST"])
def autoselection_skip():
    try:
        data = request.get_json()

        name = data.get("name")
        year = data.get("year")

        removed = False
        key_to_set_event = None
        for key, sel in list(selector.selection_requests.items()):
            if sel['combination'].name == name and sel['combination'].year == year:
                del selector.selection_requests[key]
                removed = True
                key_to_set_event = sel['combination'].name
                break

        # Trigger the event to unblock choose_movie
        if key_to_set_event and key_to_set_event in selector.selection_events:
            selector.selection_results[key_to_set_event] = None  # indicate skipped
            selector.selection_events[key_to_set_event].set()  # unblock the waiting thread

        if removed:
            return jsonify(success=True, message=f"Skipped {name} ({year})")
        else:
            return jsonify(success=False, message="Selection not found")
    except Exception as e:
        return jsonify(success=False, message=str(e))

def main():
    global plex, movies

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.FileHandler('ltp.log', encoding='utf-8')]
    )

    parser = argparse.ArgumentParser(prog='LetterboxdToPlex',
                                     description='Tool to export movie information from Plex to Letterboxd and vice versa')
    parser.add_argument('-r', '--rating', action='store_true', help='exports Letterboxd ratings to Plex movies')
    parser.add_argument('-o', '--owned', type=int, nargs='?', const=-1,
                        help='creates a csv file to import to a Letterboxd list. ' +
                             'Used to get the \'owned\' filter. If number is passed after, only that amount of recent movies ' +
                             'will get processed')
    parser.add_argument('-w', '--watchlist', action='store_true',
                        help='exports movies from Letterboxd watchlist to Plex')
    parser.add_argument('--web', action='store_true', help='starting web server')
    args = parser.parse_args()

    logger = logging.getLogger('')
    logger.setLevel(level=logging.INFO)

    if not os.path.exists("data"): os.mkdir("data")
    if not os.path.exists("config"): os.mkdir("config")

    try:
        plex = PlexServer(config.baseurl, config.token)
        movies = plex.library.section('Movies')
    except Exception:
        logger.error("Not able to connect to Plex")

    if config.tmdb_use_api:
        tmdb.create_table()
        tmdb.reorganize_indexes()
        tmdb.invalidate_cache()
        letterboxd.create_table()

    if args.web:
        config.web_mode = True

        print("Starting server http://localhost:5000 ...")
        app.run(host="0.0.0.0", port=5000, debug=False)
        return

    if not args.web:
        if args.watchlist or (args.owned is None and not args.rating):
            run_watchlist(logger)
        if args.owned is not None:
            run_owned(logger, args.owned)
        if args.rating:
            run_rating(logger)

    print("Done")


if __name__ == "__main__":
    main()
