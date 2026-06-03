import argparse
import os
import json
import logging
import queue
import threading
import time
import inspect
from pathlib import Path

from flask import Flask, jsonify, request, Response, render_template
from enum import Enum

import csv
import config
import letterboxd
import owned
import rating
import tmdb
import watchlist
import util
import zipfile
import selector

from session import Session
from plexapi.myplex import PlexServer

app = Flask(__name__)

plex = None
movies = None

TASK_LOG_LIMIT = 200
THREAD_TASKS = {"watchlist", "rating"}
task_states = {}
task_listeners = {}
task_state_lock = threading.Lock()


def load_json(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=3, ensure_ascii=False)


def log_progress(progress_callback, message):
    if progress_callback:
        progress_callback(str(message))


def _existing_paths(paths):
    resolved = []
    for path in paths:
        found = util.resolve_existing_path(path)
        if found:
            resolved.append(found)
    return resolved


def _extract_export_archive(zipfile_name, progress_callback=None):
    log_progress(progress_callback, f"Extracting Letterboxd export archive from '{zipfile_name}'...")
    with zipfile.ZipFile(zipfile_name, 'r') as zip_ref:
        zip_ref.extractall('.')


def _find_local_export_zip(zipfile_name='letterboxd_export.zip'):
    candidates = [
        zipfile_name,
        os.path.join("data", zipfile_name),
    ]

    downloads_dir = Path.home() / "Downloads"
    if downloads_dir.exists():
        for pattern in ("letterboxd_export*.zip", "letterboxd-*.zip", "letterboxd*.zip"):
            candidates.extend(str(path) for path in downloads_dir.glob(pattern))

    existing = [path for path in candidates if os.path.exists(path)]
    if not existing:
        return None

    return max(existing, key=os.path.getmtime)


def _required_export_paths(task_name):
    required = []

    if task_name == "watchlist":
        required.append(config.watchlist_path)
        if config.include_watched_not_rated:
            required.extend([config.watched_path, config.ratings_path])
    elif task_name == "rating":
        required.append(config.ratings_path)

    seen = set()
    unique_required = []
    for path in required:
        if path not in seen:
            unique_required.append(path)
            seen.add(path)
    return unique_required


def _export_fallback_paths(task_name):
    paths = _required_export_paths(task_name)

    optional_paths = []
    if task_name == "watchlist" and config.include_watched_not_rated:
        optional_paths.extend([config.watched_path, config.ratings_path])
    elif task_name != "rating":
        optional_paths.extend([config.watchlist_path, config.watched_path, config.ratings_path])

    for path in optional_paths:
        if path not in paths:
            paths.append(path)

    return paths


def lb_export(task_name=None, progress_callback=None):
    if not config.use_api:
        return

    zipfile_name = 'letterboxd_export.zip'
    skip_download = False
    required_paths = _required_export_paths(task_name)
    fallback_paths = _export_fallback_paths(task_name)

    if os.path.exists(zipfile_name):
        mtime = os.path.getmtime(zipfile_name)
        age_seconds = time.time() - mtime
        if age_seconds < 5 * 60:
            skip_download = True

    if skip_download:
        log_progress(progress_callback, "Using recent Letterboxd export from disk...")
        _extract_export_archive(zipfile_name, progress_callback)
        return

    existing_required = _existing_paths(required_paths)
    if required_paths and len(existing_required) == len(required_paths):
        log_progress(
            progress_callback,
            "Using existing extracted Letterboxd CSV files before attempting login... "
            f"Found: {', '.join(existing_required)}"
        )
        return

    try:
        log_progress(progress_callback, "Signing in to Letterboxd...")
        session = Session(config.api_username, config.api_password, config.api_use_2fa_code)
        log_progress(progress_callback, "Downloading latest Letterboxd export...")
        session.download_export_data(zipfile_name)
        _extract_export_archive(zipfile_name, progress_callback)
        return
    except Exception as exc:
        log_progress(progress_callback, f"Letterboxd download blocked, checking local fallback... ({exc})")

    discovered_zip = _find_local_export_zip(zipfile_name)
    if discovered_zip:
        log_progress(
            progress_callback,
            "Using local Letterboxd export ZIP fallback because live login/download failed. "
            f"Found: {discovered_zip}"
        )
        _extract_export_archive(discovered_zip, progress_callback)
        return

    if os.path.exists(zipfile_name):
        log_progress(progress_callback, "Using existing export ZIP as fallback because live login/download failed.")
        _extract_export_archive(zipfile_name, progress_callback)
        return

    existing_fallback = _existing_paths(fallback_paths)
    if existing_fallback:
        log_progress(
            progress_callback,
            "Using local Letterboxd CSV fallback because live login/download failed. "
            f"Found: {', '.join(existing_fallback)}"
        )
        return

    missing_required = [path for path in required_paths if util.resolve_existing_path(path) is None]
    if missing_required:
        raise Exception(
            "Letterboxd login/download was blocked by Cloudflare and no usable local export fallback was found. "
            f"Missing files: {', '.join(missing_required)}"
        )

    raise Exception(
        "Letterboxd login/download was blocked by Cloudflare and no usable local export fallback was found."
    )


def run_watchlist(logger, progress_callback=None):
    lb_export("watchlist", progress_callback)

    logger.name = 'WATCHLIST'
    watchlist.watchlist(plex, movies, logger, progress_callback)
    return "Imported watchlist"

def run_owned(logger, amount=200):
    logger.name = 'OWNED'
    return owned.create_csv(movies, amount, logger)

def run_rating(logger, progress_callback=None):
    lb_export("rating", progress_callback)

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
    path = str(path)
    names = set()
    row_count = 0

    candidate_paths = [path]
    if not os.path.isabs(path):
        candidate_paths.append(os.path.join("lb", os.path.basename(path)))

    existing_path = next((p for p in candidate_paths if os.path.exists(p)), None)
    if not existing_path:
        return names, None, row_count

    resolved_path = str(existing_path)

    with open(resolved_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_count += 1
            name = (
                row.get("Name")
                or row.get("name")
                or row.get("Title")
                or row.get("title")
                or ""
            ).strip().lower()
            if name:
                names.add(name)
    return names, resolved_path, row_count


def _empty_task_state(task_name):
    return {
        "name": task_name,
        "running": False,
        "status": "idle",
        "message": "",
        "logs": [],
        "started_at": None,
        "finished_at": None,
        "updated_at": None,
    }


def _copy_task_state(task_name):
    with task_state_lock:
        state = dict(task_states.get(task_name, _empty_task_state(task_name)))
    state["logs"] = list(state.get("logs", []))
    return state


def _append_task_log(task_name, message, notify=True):
    if message is None:
        return

    text = str(message)
    with task_state_lock:
        state = task_states.setdefault(task_name, _empty_task_state(task_name))
        state["logs"] = (state.get("logs", []) + [text])[-TASK_LOG_LIMIT:]
        state["message"] = text
        state["updated_at"] = time.time()
        listeners = list(task_listeners.get(task_name, [])) if notify else []

    for listener in listeners:
        listener.put(text)


def _start_task_state(task_name, message):
    with task_state_lock:
        state = task_states.setdefault(task_name, _empty_task_state(task_name))
        state.update({
            "running": True,
            "status": "running",
            "message": message,
            "logs": [message],
            "started_at": time.time(),
            "finished_at": None,
            "updated_at": time.time(),
        })


def _finish_task_state(task_name, status, message):
    with task_state_lock:
        state = task_states.setdefault(task_name, _empty_task_state(task_name))
        state["running"] = False
        state["status"] = status
        state["message"] = message
        state["finished_at"] = time.time()
        state["updated_at"] = time.time()


def _is_task_running(task_name):
    with task_state_lock:
        return bool(task_states.get(task_name, {}).get("running"))


def _add_task_listener(task_name, listener):
    with task_state_lock:
        task_listeners.setdefault(task_name, []).append(listener)


def _remove_task_listener(task_name, listener):
    with task_state_lock:
        listeners = task_listeners.get(task_name)
        if not listeners:
            return
        if listener in listeners:
            listeners.remove(listener)
        if not listeners:
            task_listeners.pop(task_name, None)


def _close_task_streams(task_name):
    with task_state_lock:
        listeners = task_listeners.pop(task_name, [])

    for listener in listeners:
        listener.put(None)


def _most_recent_task_name(task_details):
    latest_name = None
    latest_ts = None

    for task_name, state in task_details.items():
        updated_at = state.get("updated_at")
        if updated_at is None:
            continue
        if latest_ts is None or updated_at > latest_ts:
            latest_name = task_name
            latest_ts = updated_at

    return latest_name


def _task_status_payload():
    task_details = {task_name: _copy_task_state(task_name) for task_name in sorted(THREAD_TASKS)}
    running_tasks = [task_name for task_name, state in task_details.items() if state.get("running")]
    active_task = running_tasks[0] if running_tasks else _most_recent_task_name(task_details)

    return {
        "running": bool(running_tasks),
        "task_name": active_task,
        "tasks": running_tasks,
        "active_task": active_task,
        "details": task_details,
    }


def _run_threaded_task(name):
    task_runners = {
        "watchlist": run_watchlist,
        "rating": run_rating,
    }

    if name not in task_runners:
        raise ValueError(f"Unknown threaded task '{name}'")

    if _is_task_running(name):
        return False, f"{name.capitalize()} task already running"

    start_message = f"{name.capitalize()} task started"
    _start_task_state(name, start_message)

    def run_task():
        logger = logging.getLogger(name.upper())
        logger.setLevel(logging.INFO)

        try:
            result = task_runners[name](logger, lambda msg: _append_task_log(name, msg))
            if result:
                _append_task_log(name, result)
            _finish_task_state(name, "completed", result or f"{name.capitalize()} task completed")
        except Exception as exc:
            logging.exception("Task %s failed", name)
            error_message = f"{name.capitalize()} task failed: {exc}"
            _append_task_log(name, error_message)
            _finish_task_state(name, "failed", error_message)
        finally:
            _close_task_streams(name)

    threading.Thread(target=run_task, daemon=True).start()
    return True, start_message


@app.route("/action/<name>", methods=["POST"])
def action(name):
    if name not in [
        "watchlist",
        "owned",
        "rating",
        "cleanup_missing",
        "strip_missing_years",
        "refresh_release_cache"
    ]:
        return jsonify(success=False, message=f"Unknown action '{name}'")

    if name in THREAD_TASKS:
        started, message = _run_threaded_task(name)
        return jsonify(success=started, message=message)

    elif name == "owned":
        logger = logging.getLogger('OWNED')
        logger.setLevel(logging.INFO)
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
        csv_sources = [
            ("watchlist", config.watchlist_path),
            ("watched", config.watched_path),
            ("ratings", config.ratings_path),
        ]

        source_stats = []
        for source_name, source_path in csv_sources:
            source_names, used_path, row_count = load_csv_names(source_path)
            known_names |= source_names
            source_stats.append({
                "source": source_name,
                "configured_path": source_path,
                "used_path": used_path,
                "rows": row_count,
                "unique_names": len(source_names),
            })

        if not known_names:
            return jsonify(
                success=False,
                message="No CSV movie names found. Cleanup skipped to avoid deleting all missing entries.",
                details=source_stats,
            )

        original_count = len(missing)

        cleaned = []
        for m in missing:
            missing_name = str(m.get("name", "")).strip().lower()
            if missing_name in known_names:
                cleaned.append(m)

        with open(config.missing_path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=2)

        removed_count = original_count - len(cleaned)
        return jsonify(
            success=True,
            message=f"Removed {removed_count} stale entries from missing list",
            details=source_stats,
        )

    elif name == "strip_missing_years":
        with open(config.missing_path, "r", encoding="utf-8") as f:
            missing = json.load(f)

        changed = 0

        for m in missing:
            if m.get("release_date") is not None:
                m["release_date"] = None
                changed += 1

        with open(config.missing_path, "w", encoding="utf-8") as f:
            json.dump(missing, f, indent=2)

        return jsonify(
            success=True,
            message=f"Cleaned years from {changed} missing entries"
        )

    elif name == "refresh_release_cache":
        with open(config.missing_path, "r", encoding="utf-8") as f:
            missing = json.load(f)

        refreshed = 0
        changed = 0
        unresolved = 0

        for m in missing:
            lb_name = m.get("name", "")
            lb_year = m.get("year", "")

            if not lb_name or not lb_year:
                continue

            try:
                movie_id = tmdb.get_tmdb_id_for_letterboxd_movie(lb_name, str(lb_year))
                if not movie_id:
                    unresolved += 1
                    continue

                best_overall = tmdb.get_configured_release_date_for_movie(movie_id, refresh=True)
                refreshed += 1

                previous = m.get("release_date")
                if best_overall != previous:
                    m["release_date"] = best_overall
                    changed += 1
            except Exception:
                pass

        with open(config.missing_path, "w", encoding="utf-8") as f:
            json.dump(missing, f, indent=2)

        return jsonify(
            success=True,
            message=(
                f"Refreshed TMDB release cache for {refreshed} missing entries; "
                f"updated {changed} release dates in missing list"
                + (f" ({unresolved} entries without TMDB id skipped)" if unresolved else "")
            )
        )

@app.route("/stream/<task_name>")
def stream_task(task_name):
    if task_name not in THREAD_TASKS:
        return "Unknown task", 404

    state = _copy_task_state(task_name)
    replay_history = request.args.get("replay", "1") != "0"
    if not state["logs"] and not state["running"]:
        return "No task data available", 404

    listener = queue.Queue()
    if state["running"]:
        _add_task_listener(task_name, listener)

    def generate():
        try:
            if replay_history:
                for msg in state["logs"]:
                    yield f"data: {msg}\n\n"

            if not state["running"]:
                return

            while True:
                msg = listener.get()
                if msg is None:
                    break
                yield f"data: {msg}\n\n"
        finally:
            _remove_task_listener(task_name, listener)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@app.route("/task/status")
def task_status():
    return jsonify(_task_status_payload())


@app.route("/tmdb/releases/<movie_id>")
def tmdb_releases(movie_id):
    try:
        releases = tmdb.get_release_dates(movie_id)
        releases = tmdb.get_first_release_per_type(releases)
        return jsonify({
            "success": True,
            "movie_id": movie_id,
            "count": len(releases),
            "releases": releases,
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "movie_id": movie_id,
            "message": str(e),
        }), 500


@app.route("/tmdb/releases/by-missing")
def tmdb_releases_by_missing():
    name = request.args.get("name", "")
    year = request.args.get("year", "")

    if not name or not year:
        return jsonify({
            "success": False,
            "message": "Missing required query parameters: name and year",
        }), 400

    try:
        movie_id, releases = tmdb.get_release_dates_for_letterboxd_movie(name, year)
        releases = tmdb.get_first_release_per_type(releases)
        return jsonify({
            "success": True,
            "name": name,
            "year": year,
            "movie_id": movie_id,
            "count": len(releases),
            "releases": releases,
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e),
        }), 500


@app.route("/tmdb/releases/by-missing/fetch")
def tmdb_releases_by_missing_fetch():
    """
    Gets release dates for a Letterboxd movie, fetching from TMDB API on-demand if not cached.
    This endpoint is used by the UI when a modal is opened and no cached releases exist.
    """
    name = request.args.get("name", "")
    year = request.args.get("year", "")

    if not name or not year:
        return jsonify({
            "success": False,
            "message": "Missing required query parameters: name and year",
        }), 400

    try:
        movie_id, releases = tmdb.get_release_dates_for_letterboxd_movie_with_fetch(name, year)
        releases = tmdb.get_first_release_per_type(releases)
        return jsonify({
            "success": True,
            "name": name,
            "year": year,
            "movie_id": movie_id,
            "count": len(releases),
            "releases": releases,
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e),
        }), 500

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

    # Always merge in any new keys from config.py that aren't in the file yet
    for key in dir(config):
        if key.startswith("_") or not key.islower():
            continue
        if key in cfg:
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
            current_value = getattr(config, key, None)

            if isinstance(current_value, Enum) and isinstance(value, str):
                enum_class = type(current_value)
                enum_name = value.split(".")[-1] if "." in value else value
                if enum_name in enum_class.__members__:
                    value = enum_class[enum_name]

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

    os.makedirs("data", exist_ok=True)
    os.makedirs("config", exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.FileHandler(os.path.join("data", "ltp.log"), encoding='utf-8')]
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
