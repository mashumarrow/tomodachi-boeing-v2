import json
import math
import mimetypes
import os
import sqlite3
from contextlib import closing
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.error import URLError

import jwt
from user_records import (auth_config, authenticated_subject, list_records, save_record,
                          get_profile, save_profile, MIYAZAKI_UNIVERSITY_ID,
                          list_reviews, verified_email_university, validate_record, publish_all_reviews,
                          email_verification_status, sync_review_email_badges,
                          hospital_stay_averages, hospital_fee_averages)
from university_locations import resolve_university_location


ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "data" / "facilities.sqlite3"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))


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

    def end_headers(self):
        if urlparse(self.path).path in {"/", "/index.html", "/app.js", "/styles.css", "/ui.generated.css"}:
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/auth-config":
            self.send_json(auth_config())
            return
        if parsed.path == "/api/visits":
            subject = self.require_member()
            if subject:
                self.send_json({"visits": list_records(subject)})
            return
        if parsed.path == "/api/reviews":
            subject = self.require_member()
            if not subject:
                return
            hospital_id = parse_qs(parsed.query).get("hospitalId", [""])[0]
            if not hospital_id or len(hospital_id) > 300:
                self.send_json({"error": "病院を指定してください。"}, 400)
                return
            self.send_json({"reviews": list_reviews(subject, hospital_id)})
            return
        if parsed.path == "/api/facilities":
            subject = self.require_member()
            if not subject:
                return
            self.handle_facilities(parse_qs(parsed.query), subject)
            return
        if parsed.path == "/api/university-origin":
            subject = self.require_member()
            if not subject:
                return
            try:
                location = resolve_university_location(MIYAZAKI_UNIVERSITY_ID)
                self.send_json({"origin": location})
            except (ValueError, URLError, TimeoutError, KeyError, TypeError):
                self.send_json({"error": "大学の所在地を取得できませんでした。時間をおいて再度検索してください。"}, 503)
            return
        if parsed.path == "/api/profile":
            subject = self.require_user()
            if subject:
                self.send_json({"profile": get_profile(subject)})
            return
        if parsed.path not in {"/", "/index.html", "/app.js", "/styles.css", "/ui.generated.css", "/assets/icons/log-out.svg", "/assets/universities/miyazaki-symbol.png"}:
            self.send_json({"error": "Not found"}, 404)
            return
        super().do_GET()

    def do_HEAD(self):
        if urlparse(self.path).path not in {"/", "/index.html", "/app.js", "/styles.css", "/ui.generated.css", "/assets/icons/log-out.svg", "/assets/universities/miyazaki-symbol.png"}:
            self.send_error(404)
            return
        super().do_HEAD()

    def require_user(self):
        try:
            return authenticated_subject(self.headers.get("Authorization", ""))
        except RuntimeError:
            self.send_json({"error": "Auth0の設定が未完了です。"}, 503)
        except jwt.PyJWKClientConnectionError:
            self.send_json({"error": "Auth0の署名鍵を取得できません。サーバーのインターネット接続を確認してください。", "code": "auth_key_unavailable"}, 503)
        except jwt.ExpiredSignatureError:
            self.send_json({"error": "ログインの有効期限が切れました。再度ログインしてください。", "code": "token_expired"}, 401)
        except jwt.ImmatureSignatureError:
            self.log_error("Authentication rejected: token_not_yet_valid")
            self.send_json({"error": "トークンの有効開始時刻とサーバー時刻が一致しません。PC・サーバーの日時を自動設定にしてください。", "code": "token_not_yet_valid"}, 401)
        except jwt.InvalidAudienceError:
            self.send_json({"error": "トークンのAudienceとAPI Identifierが一致しません。", "code": "invalid_audience"}, 401)
        except jwt.InvalidIssuerError:
            self.send_json({"error": "トークンの発行元とAuth0 Domainが一致しません。", "code": "invalid_issuer"}, 401)
        except jwt.InvalidAlgorithmError:
            self.send_json({"error": "Auth0 APIの署名方式をRS256に設定し、ログインし直してください。", "code": "invalid_algorithm"}, 401)
        except jwt.InvalidSignatureError:
            self.send_json({"error": "トークンの署名を検証できません。ログインし直してください。", "code": "invalid_signature"}, 401)
        except jwt.DecodeError:
            self.send_json({"error": "API用の署名付きトークンを読み取れません。Auth0 APIのIdentifier・RS256・トークン暗号化設定を確認してください。", "code": "invalid_token_format"}, 401)
        except jwt.PyJWKClientError:
            self.send_json({"error": "トークンに対応する公開鍵がありません。Auth0 APIの署名方式とDomainを確認してください。", "code": "signing_key_not_found"}, 401)
        except jwt.InvalidTokenError as error:
            self.log_error("Authentication rejected: %s", type(error).__name__)
            self.send_json({"error": "ログイントークンが無効です。再度ログインしてください。", "code": "invalid_token"}, 401)
        return None

    def require_member(self):
        subject = self.require_user()
        if not subject:
            return None
        profile = get_profile(subject)
        if not profile:
            self.send_json({"error": "プロフィールを登録してください。", "code": "profile_required"}, 403)
            return None
        if profile.get("universityId") != MIYAZAKI_UNIVERSITY_ID:
            self.send_json({"error": "宮崎大学向けのプロフィールを登録してください。", "code": "miyazaki_required"}, 403)
            return None
        return subject

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/email-verification":
            subject = self.require_user()
            if not subject:
                return
            try:
                status = email_verification_status(subject, self.headers.get("Authorization", ""))
            except (URLError, TimeoutError, ValueError):
                self.send_json({"error": "大学メールの認証状態を確認できませんでした。再ログインしてから試してください。"}, 503)
                return
            updated = (sync_review_email_badges(subject, status["verifiedEmailUniversity"])
                       if status["universityEmailVerified"] is True else 0)
            self.send_json({**status, "updatedReviews": updated})
            return
        if path not in {"/api/visits", "/api/profile"}:
            self.send_json({"error": "Not found"}, 404)
            return
        subject = self.require_user() if path == "/api/profile" else self.require_member()
        if not subject:
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384:
                raise ValueError("記録のサイズが正しくありません。")
            payload = json.loads(self.rfile.read(length))
            if path == "/api/profile":
                record = save_profile(subject, payload)
                publish_all_reviews(subject)
            else:
                payload = validate_record(payload)
                payload["reviewSharing"]["published"] = True
                verified = None
                if payload["reviewSharing"]["published"] and payload["reviewVersion"] == 2:
                    try:
                        verified = verified_email_university(subject, self.headers.get("Authorization", ""))
                    except (URLError, TimeoutError, ValueError):
                        self.log_error("University email verification unavailable; no badge issued")
                record = save_record(subject, payload, verified_email_university=verified)
        except (ValueError, UnicodeDecodeError) as error:
            self.send_json({"error": str(error)}, 400)
            return
        self.send_json({"profile" if path == "/api/profile" else "visit": record}, 201)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/reviews":
            self.send_json({"error": "Not found"}, 404)
            return
        subject = self.require_member()
        if not subject:
            return
        self.send_json({"error": "口コミはすべて公開されます。公開の切り替えはできません。"}, 405)

    def handle_facilities(self, query, subject):
        try:
            latitude = float(query["latitude"][0])
            longitude = float(query["longitude"][0])
            radius = min(50.0, max(1.0, float(query.get("radius", ["12"])[0])))
            limit = min(200, max(1, int(query.get("limit", ["100"])[0])))
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
              AND f.address LIKE '宮崎県%'
              AND f.type IN ('hospital', 'clinic')
              AND EXISTS (
                  SELECT 1 FROM facility_departments fd
                  WHERE fd.facility_id = f.id AND fd.department = ?
              )
        """

        with closing(sqlite3.connect(DATABASE)) as connection:
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
        visible_results = results[:limit]
        hospital_ids = [facility["id"] for facility in visible_results]
        averages = hospital_stay_averages(subject, hospital_ids)
        fee_averages = hospital_fee_averages(subject, hospital_ids)
        for facility in visible_results:
            facility.update(averages.get(facility["id"], {"averageStayMinutes": None, "staySampleCount": 0}))
            facility.update(fee_averages.get(facility["id"], {"averageFeeAmount": None, "feeSampleCount": 0}))
        self.send_json({"facilities": visible_results, "total": len(results)})

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
    print(f"Published historical reviews: {publish_all_reviews()}")
    print(f"Campus Clinic Finder: http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), AppHandler).serve_forever()
