import json
import math
import threading
import time
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from user_records import UNIVERSITIES, connect_records


# Existing campus locations, indexed by the MEXT school code.
CAMPUS_LOCATIONS = {
    "F145110111523": (31.8310233, 131.4125839, "木花キャンパス"),
    "F126310107564": (35.0299, 135.7608, "今出川キャンパス"),
}
LOOKUP_LOCK = threading.Lock()
LAST_REQUEST = 0.0


def resolve_university_location(university_id):
    university = UNIVERSITIES.get(university_id)
    if not university:
        raise ValueError("大学が見つかりません。プロフィールを確認してください。")
    if university_id in CAMPUS_LOCATIONS:
        latitude, longitude, campus = CAMPUS_LOCATIONS[university_id]
        return {"label": f"{university['name']} {campus}", "latitude": latitude,
                "longitude": longitude, "address": university["address"], "source": "campus"}

    with LOOKUP_LOCK:
        with connect_records() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS university_locations "
                               "(school_id TEXT PRIMARY KEY, address TEXT NOT NULL, payload TEXT NOT NULL)")
            row = connection.execute("SELECT payload FROM university_locations WHERE school_id = ? AND address = ?",
                                     (university_id, university["address"])).fetchone()
        if row:
            return json.loads(row[0])
        location = lookup_address(university)
        with connect_records() as connection:
            connection.execute("INSERT INTO university_locations (school_id, address, payload) VALUES (?, ?, ?) "
                               "ON CONFLICT(school_id) DO UPDATE SET address = excluded.address, payload = excluded.payload",
                               (university_id, university["address"], json.dumps(location, ensure_ascii=False)))
        return location


def lookup_address(university):
    global LAST_REQUEST
    delay = 1.0 - (time.monotonic() - LAST_REQUEST)
    if delay > 0:
        time.sleep(delay)
    LAST_REQUEST = time.monotonic()
    address = unicodedata.normalize("NFKC", university["address"])
    url = "https://msearch.gsi.go.jp/address-search/AddressSearch?" + urlencode({"q": address})
    request = Request(url, headers={"User-Agent": "CampusClinicFinder/1.0"})
    with urlopen(request, timeout=12) as response:
        results = json.load(response)
    if not results:
        raise ValueError("大学の所在地を取得できませんでした。「現在地を使う」で検索してください。")
    longitude, latitude = results[0]["geometry"]["coordinates"][:2]
    if not (math.isfinite(latitude) and math.isfinite(longitude)
            and 20 <= latitude <= 46 and 122 <= longitude <= 154):
        raise ValueError("大学の所在地が不正です。「現在地を使う」で検索してください。")
    return {"label": university["name"], "latitude": latitude, "longitude": longitude,
            "address": university["address"], "matchedAddress": results[0]["properties"]["title"], "source": "gsi"}
