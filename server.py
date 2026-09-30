import json
import math
import mimetypes
import sqlite3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "data" / "facilities.sqlite3"
HOST = "127.0.0.1"
PORT = 8000


def haversine(latitude, longitude, target_latitude, target_longitude):
    radius = 6371
    lat1 = math.radians(latitude)
    lat2 = math.radians(target_latitude)
    lat_delta = math.radians(target_latitude - latitude)
    lon_delta = math.radians(target_longitude - longitude)
    value = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(lon_delta / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/facilities":
            self.handle_facilities(parse_qs(parsed.query))
            return
        super().do_GET()

    def handle_facilities(self, query):
        try:
            latitude = float(query["latitude"][0])
            longitude = float(query["longitude"][0])
            radius = min(50.0, max(1.0, float(query.get("radius", ["12"])[0])))
            limit = min(200, max(1, int(query.get("limit", ["100"])[0])))
            facility_type = query.get("type", ["medical"])[0]
            department = query.get("department", [""])[0]
        except (KeyError, ValueError, IndexError):
            self.send_json({"error": "検索条件が正しくありません"}, 400)
            return

        if not DATABASE.exists():
            self.send_json({"error": "施設DBがありません。生成スクリプトを実行してください"}, 503)
            return

        latitude_delta = radius / 111.0
        longitude_scale = max(0.1, math.cos(math.radians(latitude)))
        longitude_delta = radius / (111.0 * longitude_scale)
        parameters = [
            latitude - latitude_delta,
            latitude + latitude_delta,
            longitude - longitude_delta,
            longitude + longitude_delta,
        ]
        type_clause = "f.type = 'pharmacy'"
        department_clause = ""
        if facility_type != "pharmacy":
            type_clause = "f.type IN ('hospital', 'clinic')"
            department_clause = """
                AND EXISTS (
                    SELECT 1 FROM facility_departments fd
                    WHERE fd.facility_id = f.id AND fd.department = ?
                )
            """
            parameters.append(department)

        sql = f"""
            SELECT
                f.id, f.type, f.name, f.address, f.latitude, f.longitude,
                f.website, f.open, f.median_wait,
                (SELECT GROUP_CONCAT(fd.department)
                 FROM facility_departments fd WHERE fd.facility_id = f.id) AS departments
            FROM facilities f
            WHERE f.latitude BETWEEN ? AND ?
              AND f.longitude BETWEEN ? AND ?
              AND {type_clause}
              {department_clause}
        """

        with sqlite3.connect(DATABASE) as connection:
            connection.row_factory = sqlite3.Row
            candidates = connection.execute(sql, parameters).fetchall()

        results = []
        for row in candidates:
            distance = haversine(latitude, longitude, row["latitude"], row["longitude"])
            if distance > radius:
                continue
            results.append({
                "id": row["id"],
                "type": row["type"],
                "name": row["name"],
                "address": row["address"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "distanceKm": round(distance, 2),
                "departments": (row["departments"] or "").split(","),
                "website": row["website"],
                "maps": (
                    "https://www.google.com/maps/search/?api=1&query="
                    f"{row['latitude']},{row['longitude']}"
                ),
                "open": row["open"],
                "medianWait": row["median_wait"],
                "samples": 0,
                "feeLow": None,
                "feeHigh": None,
                "p60": None,
                "p90": None,
                "phone": "掲載なし",
            })
        results.sort(key=lambda item: item["distanceKm"])
        self.send_json({"facilities": results[:limit], "total": len(results)})

    def send_json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    mimetypes.add_type("application/javascript", ".js")
    print(f"Campus Clinic Finder: http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), AppHandler).serve_forever()
