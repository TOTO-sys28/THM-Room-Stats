from flask import Flask, jsonify, render_template, request
import re
import time

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

app = Flask(__name__, static_folder="static", template_folder="static")

PROFILE_ENDPOINT = "https://tryhackme.com/api/v2/public-profile"
ROOMS_ENDPOINT = "https://tryhackme.com/api/v2/public-profile/completed-rooms"
PAGE_SIZE = 50
MAX_PAGES = 10
CACHE_TTL = 300
cache = {}

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,50}$")
PROFILE_RE = re.compile(r"tryhackme\.com/(?:p|profile)/([A-Za-z0-9_-]{2,50})/?$", re.I)


def normalize_username(value: str) -> str:
    value = (value or "").strip()
    value = value.split("?", 1)[0].split("#", 1)[0].rstrip("/")

    # Accept a bare username.
    if USERNAME_RE.fullmatch(value):
        return value

    # Accept https://tryhackme.com/p/<username> and /profile/<username>.
    match = PROFILE_RE.search(value.replace("https://", "").replace("http://", ""))
    if match:
        return match.group(1)

    # Also accept the common pasted form with www.
    value2 = value.replace("www.", "")
    match = PROFILE_RE.search(value2)
    if match:
        return match.group(1)

    raise ValueError("Enter a TryHackMe username or profile URL like https://tryhackme.com/p/username")


def thm_session():
    if curl_requests is None:
        raise RuntimeError(
            "Missing dependency: curl_cffi. Run: pip install -r requirements.txt"
        )

    session = curl_requests.Session(impersonate="chrome")
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 "
                "THM-Room-Stats/1.0"
            ),
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://tryhackme.com/",
            "Origin": "https://tryhackme.com",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
    )
    return session


def request_json(session, url, *, params=None, attempts=2):
    last_status = None
    for attempt in range(attempts):
        response = session.get(url, params=params, timeout=20)
        last_status = response.status_code

        content_type = (response.headers.get("content-type") or "").lower()
        if 200 <= response.status_code < 300:
            try:
                return response.json()
            except ValueError:
                preview = response.text[:180].replace("\n", " ").replace("\r", " ")
                raise RuntimeError(
                    "TryHackMe returned a non-JSON response "
                    f"(content-type: {content_type or 'unknown'}): {preview}"
                )

        # 429 can be a transient edge/bot-mitigation response.
        if response.status_code == 429 and attempt + 1 < attempts:
            retry_after = response.headers.get("Retry-After")
            try:
                delay = min(max(float(retry_after), 1.0), 8.0)
            except (TypeError, ValueError):
                delay = 2.0
            time.sleep(delay)
            continue

        body = response.text[:300].replace("\n", " ")
        raise RuntimeError(
            f"TryHackMe returned HTTP {response.status_code}. {body}"
        )

    raise RuntimeError(f"TryHackMe returned HTTP {last_status}.")


def fetch_profile(session, username):
    data = request_json(session, PROFILE_ENDPOINT, params={"username": username})
    if not isinstance(data, dict) or data.get("status") != "success":
        raise RuntimeError("TryHackMe profile was not found or is not public.")

    profile = data.get("data")
    if not isinstance(profile, dict):
        raise RuntimeError("TryHackMe returned an unexpected profile response.")
    return profile


def normalize_difficulty(value):
    value = str(value or "").strip().lower()
    if value in {"easy", "medium", "hard", "insane"}:
        return value
    return "unknown"


def fetch_completed_rooms(session, username):
    all_rooms = []
    for page in range(1, MAX_PAGES + 1):
        data = request_json(
            session,
            ROOMS_ENDPOINT,
            params={"username": username, "limit": PAGE_SIZE, "page": page},
        )

        # Current THM v2 shape:
        # {"status":"success", "data":{"docs":[...], "hasNextPage": bool}}
        if not isinstance(data, dict):
            raise RuntimeError("TryHackMe returned an unexpected rooms response.")

        payload = data.get("data")
        if not isinstance(payload, dict):
            raise RuntimeError("TryHackMe returned an unexpected rooms payload.")

        docs = payload.get("docs")
        if not isinstance(docs, list):
            raise RuntimeError("TryHackMe returned no completed-room list.")

        all_rooms.extend(room for room in docs if isinstance(room, dict))

        if not payload.get("hasNextPage"):
            break

        time.sleep(0.35)

    return all_rooms


def get_stats(username):
    cached = cache.get(username)
    now = time.time()
    if cached and now - cached["time"] < CACHE_TTL:
        return cached["data"]

    session = thm_session()
    profile = fetch_profile(session, username)
    rooms = fetch_completed_rooms(session, username)

    counts = {"easy": 0, "medium": 0, "hard": 0, "insane": 0, "unknown": 0}
    cleaned_rooms = []
    seen = set()

    for room in rooms:
        if not isinstance(room, dict):
            continue
        code = room.get("code")
        title = room.get("title") or code or "Unknown room"
        difficulty = normalize_difficulty(room.get("difficulty"))
        key = code or f"{title}:{difficulty}"
        if key in seen:
            continue
        seen.add(key)
        counts[difficulty] += 1
        cleaned_rooms.append({
            "title": title,
            "code": code,
            "difficulty": difficulty,
        })

    # The v2 profile reports THM's own completed-room count. The room API is
    # used only for the difficulty breakdown, so we expose both values.
    reported_total = profile.get("completedRoomsNumber")
    total = len(cleaned_rooms)
    if isinstance(reported_total, int) and reported_total >= 0:
        total_reported = reported_total
    else:
        total_reported = total

    result = {
        "username": profile.get("username") or username,
        "profile_url": f"https://tryhackme.com/p/{username}",
        "level": profile.get("level"),
        "rank": None,
        "top_percentage": profile.get("topPercentage"),
        "total_points": profile.get("totalPoints"),
        "badges": profile.get("badgesNumber"),
        "streak": profile.get("streak"),
        "largest_streak": profile.get("largestStreak"),
        "reported_total": total_reported,
        "breakdown_total": total,
        "total": total_reported,
        "easy": counts["easy"],
        "medium": counts["medium"],
        "hard": counts["hard"],
        "insane": counts["insane"],
        "unknown": counts["unknown"],
        "rooms": cleaned_rooms,
        "cached_for_seconds": CACHE_TTL,
    }

    cache[username] = {"time": now, "data": result}
    return result


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/stats")
def api_stats():
    raw_username = request.args.get("username", "")

    try:
        username = normalize_username(raw_username)
        return jsonify(get_stats(username))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        message = str(exc)
        if "HTTP 429" in message:
            message = (
                "TryHackMe rate-limited this request (HTTP 429). "
                "The app is already using Chrome TLS impersonation; wait a little and retry."
            )
        return jsonify({"error": message}), 502
    except Exception as exc:
        app.logger.exception("Unexpected error")
        return jsonify({"error": f"Unexpected error: {exc}"}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
