import json
import os
import runpy
import sqlite3
import tempfile
import time
import unittest
import threading
from contextlib import closing
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import load_dotenv

import user_records
import university_locations
from server import AppHandler


class UserRecordTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_patch = patch.object(user_records, "RECORDS_DATABASE",
                                           Path(self.directory.name) / "records.sqlite3")
        self.database_patch.start()
        self.record = {
            "id": "visit-1", "hospitalId": "clinic:1", "hospitalName": "Clinic",
            "department": "internal", "plannedAt": "2026-10-12T00:00:00Z",
            "arrivalAt": "2026-10-12T00:10:00Z", "leaveAt": "2026-10-12T00:45:00Z",
            "feeAmount": "1200", "reservationStatus": "予約なし", "waitingImpression": "スムーズ",
        }

    def tearDown(self):
        self.database_patch.stop()
        self.directory.cleanup()

    def test_records_belong_to_authenticated_user(self):
        user_records.save_record("user-a", {**self.record, "user_id": "user-b", "stayMinutes": 999})
        self.assertEqual(user_records.list_records("user-b"), [])
        self.assertEqual(user_records.list_records("user-a")[0]["stayMinutes"], 35)
        user_records.save_record("user-b", {**self.record, "hospitalId": "clinic:2"})
        self.assertEqual(user_records.list_records("user-a")[0]["hospitalId"], "clinic:1")
        self.assertEqual(user_records.list_records("user-b")[0]["hospitalId"], "clinic:2")

    def test_retry_does_not_duplicate_record(self):
        user_records.save_record("user-a", self.record)
        user_records.save_record("user-a", self.record)
        self.assertEqual(len(user_records.list_records("user-a")), 1)

    def test_local_settings_load_without_overriding_environment(self):
        settings = "AUTH0_DOMAIN=file.auth0.com\nAUTH0_CLIENT_ID=file-client\nAUTH0_AUDIENCE=file-api\n"
        for environment, expected in (({}, "file.auth0.com"), ({"AUTH0_DOMAIN": "deployment.auth0.com"}, "deployment.auth0.com")):
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                with patch("dotenv.load_dotenv", side_effect=lambda path, override: load_dotenv(
                    stream=StringIO(settings), override=override)) as loader:
                    module = runpy.run_path(user_records.__file__)
                loader.assert_called_once_with(Path(user_records.__file__).with_name(".env"), override=False)
                self.assertEqual(module["DOMAIN"], expected)
                self.assertEqual(module["CLIENT_ID"], "file-client")
                self.assertEqual(module["AUDIENCE"], "file-api")
                self.assertTrue(module["auth_config"]()["configured"])

    def test_review_note_round_trip_and_legacy_record(self):
        note = "診察は1841円。\n説明が丁寧でした。<b>感想</b>"
        saved = user_records.save_record("user-a", {**self.record, "note": note})
        self.assertEqual(saved["note"], note)
        self.assertEqual(user_records.list_records("user-a")[0]["note"], note)
        self.assertEqual(user_records.list_records("user-b"), [])
        self.assertEqual(user_records.validate_record(self.record)["note"], "")
        self.assertEqual(user_records.validate_record({**self.record, "note": "a" * 2000})["note"], "a" * 2000)
        for note in (None, 123, [], "a" * 2001):
            with self.subTest(note_type=type(note).__name__), self.assertRaises(ValueError):
                user_records.save_record("user-a", {**self.record, "note": note})

    def miyazaki_profile(self, subject="user-a", grade="4"):
        return user_records.save_profile(subject, {"universityId": user_records.MIYAZAKI_UNIVERSITY_ID,
                                                   "grade": grade, "gender": "female"})

    def published_record(self, **overrides):
        return {**self.record, "note": "説明が丁寧でした。", "reviewSharing": {"published": True}, **overrides}

    def test_reviews_are_private_until_explicitly_published(self):
        self.miyazaki_profile()
        user_records.save_record("user-a", {**self.record, "note": "自分用のメモ"})
        self.assertEqual(user_records.list_reviews("user-b", "clinic:1"), [])
        user_records.save_record("user-a", self.published_record(gradeBand="偽の学年", gender="female"))
        reviews = user_records.list_reviews("user-b", "clinic:1")
        self.assertEqual(len(reviews), 1)
        public = reviews[0]
        self.assertEqual(public["gradeBand"], "学部3〜4年")
        self.assertEqual(public["stayMinutes"], 35)
        self.assertEqual(public["feeAmount"], "1200")
        self.assertFalse(public["isOwnRecord"])
        self.assertNotEqual(public["id"], self.record["id"])
        self.assertEqual(set(public), {"id", "hospitalId", "note", "gradeBand", "stayMinutes", "feeAmount",
                                       "reservationStatus", "isOwnRecord"})
        user_records.save_record("user-a", self.published_record())
        self.assertEqual(len(user_records.list_reviews("user-b", "clinic:1")), 1)
        self.assertEqual(user_records.list_reviews("user-b", "clinic:2"), [])
        self.assertTrue(user_records.list_reviews("user-a", "clinic:1")[0]["isOwnRecord"])

    def test_review_field_selection_and_withdrawal_preserve_private_record(self):
        self.miyazaki_profile()
        sharing = {"published": True, **{field: False for field in user_records.REVIEW_FIELDS}}
        user_records.save_record("user-a", self.published_record(reviewSharing=sharing))
        self.assertEqual(set(user_records.list_reviews("user-b", "clinic:1")[0]),
                         {"id", "hospitalId", "note", "isOwnRecord"})
        with self.assertRaises(ValueError):
            user_records.unpublish_review("user-b", "visit-1")
        self.assertEqual(len(user_records.list_reviews("user-b", "clinic:1")), 1)
        record = user_records.unpublish_review("user-a", "visit-1")
        self.assertFalse(record["reviewSharing"]["published"])
        self.assertEqual(record["note"], "説明が丁寧でした。")
        self.assertEqual(record["arrivalAt"], self.record["arrivalAt"])
        self.assertEqual(user_records.list_reviews("user-b", "clinic:1"), [])
        self.assertEqual(len(user_records.list_records("user-a")), 1)

    def test_review_publication_requires_miyazaki_profile_and_valid_consent(self):
        with self.assertRaises(ValueError):
            user_records.save_record("user-a", self.published_record())
        self.miyazaki_profile()
        for replacement in ({"note": " "}, {"reviewSharing": {"published": "true"}},
                            {"reviewSharing": {"published": True, "showFee": 1}}, {"reviewSharing": []}):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                user_records.save_record("user-a", self.published_record(**replacement))
        user_records.save_record("user-a", self.published_record())
        other_school = next(code for code in user_records.UNIVERSITIES if code != user_records.MIYAZAKI_UNIVERSITY_ID)
        user_records.save_profile("user-a", {"universityId": other_school, "grade": "4", "gender": "female"})
        self.assertEqual(user_records.list_reviews("user-b", "clinic:1"), [])
        with self.assertRaises(ValueError):
            user_records.save_record("user-a", self.published_record())
        self.assertEqual(user_records.grade_band("1"), "学部1〜2年")
        self.assertEqual(user_records.grade_band("6"), "学部5〜6年")
        self.assertEqual(user_records.grade_band("master1"), "大学院生")

    def test_review_api_authentication_and_ownership(self):
        self.miyazaki_profile("user-a")
        self.miyazaki_profile("user-b", "2")
        user_records.save_record("user-a", self.published_record())
        app = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        thread = threading.Thread(target=app.serve_forever, daemon=True)
        thread.start()
        def request(method, path):
            connection = HTTPConnection("127.0.0.1", app.server_port)
            connection.request(method, path)
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result
        try:
            with patch("server.authenticated_subject", side_effect=jwt.InvalidTokenError("missing")):
                self.assertEqual(request("GET", "/api/reviews?hospitalId=clinic:1")[0], 401)
            with patch("server.authenticated_subject", return_value="user-b"):
                status, data = request("GET", "/api/reviews?hospitalId=clinic:1")
                self.assertEqual(status, 200)
                self.assertEqual(len(data["reviews"]), 1)
                self.assertNotIn("arrivalAt", data["reviews"][0])
                self.assertEqual(request("DELETE", "/api/reviews?visitId=visit-1")[0], 404)
            with patch("server.authenticated_subject", return_value="user-a"):
                self.assertEqual(request("DELETE", "/api/reviews?visitId=visit-1")[0], 200)
                self.assertEqual(request("GET", "/api/reviews?hospitalId=clinic:1")[1]["reviews"], [])
            other_school = next(code for code in user_records.UNIVERSITIES if code != user_records.MIYAZAKI_UNIVERSITY_ID)
            user_records.save_profile("user-b", {"universityId": other_school, "grade": "2", "gender": "female"})
            with patch("server.authenticated_subject", return_value="user-b"):
                self.assertEqual(request("GET", "/api/reviews?hospitalId=clinic:1")[0], 403)
        finally:
            app.shutdown()
            app.server_close()
            thread.join()

    def test_facility_search_excludes_pharmacies(self):
        database = Path(self.directory.name) / "facilities.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            connection.executescript("""
                CREATE TABLE facilities (
                    id TEXT, type TEXT, name TEXT, address TEXT, latitude REAL,
                    longitude REAL, website TEXT, open TEXT, median_wait INTEGER
                );
                CREATE TABLE facility_departments (facility_id TEXT, department TEXT);
            """)
            for kind in ("hospital", "clinic", "pharmacy"):
                connection.execute("INSERT INTO facilities VALUES (?, ?, ?, '', 35, 135, '', '', 30)",
                                   (kind, kind, kind))
                connection.execute("INSERT INTO facility_departments VALUES (?, 'internal')", (kind,))
            connection.commit()
        app = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        thread = threading.Thread(target=app.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("server.DATABASE", database), patch("server.authenticated_subject", return_value="user-a"):
                user_records.save_profile("user-a", {"universityId": next(iter(user_records.UNIVERSITIES)),
                                                     "grade": "1", "gender": "prefer_not_to_say"})
                for suffix in ("", "&type=pharmacy", "&type=medical"):
                    connection = HTTPConnection("127.0.0.1", app.server_port)
                    connection.request("GET", "/api/facilities?latitude=35&longitude=135&department=internal" + suffix)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    facilities = json.loads(response.read())["facilities"]
                    self.assertEqual({item["type"] for item in facilities}, {"hospital", "clinic"})
                    connection.close()
        finally:
            app.shutdown()
            app.server_close()
            thread.join()

    def test_university_origin_matches_registered_school_and_cache(self):
        miyazaki = university_locations.resolve_university_location("F145110111523")
        self.assertAlmostEqual(miyazaki["latitude"], 31.8310233)
        other = next(code for code in user_records.UNIVERSITIES if code not in university_locations.CAMPUS_LOCATIONS)
        location = {"latitude": 35.0, "longitude": 139.0, "label": "University", "source": "gsi"}
        with patch("university_locations.lookup_address", return_value=location) as lookup:
            self.assertEqual(university_locations.resolve_university_location(other), location)
            self.assertEqual(university_locations.resolve_university_location(other), location)
            lookup.assert_called_once()
        with self.assertRaises(ValueError):
            university_locations.resolve_university_location("unknown")

    def test_profile_validation_and_ownership(self):
        university = next(iter(user_records.UNIVERSITIES))
        profile = {"universityId": university, "grade": "4", "gender": "prefer_not_to_say"}
        saved = user_records.save_profile("user-a", {**profile, "user_id": "user-b"})
        self.assertEqual(saved["universityName"], user_records.UNIVERSITIES[university]["name"])
        self.assertIsNone(user_records.get_profile("user-b"))
        self.assertEqual(user_records.get_profile("user-a")["grade"], "4")
        for invalid in ({"universityId": "unknown"}, {"grade": "invalid"}, {"gender": "invalid"}):
            with self.assertRaises(ValueError):
                user_records.save_profile("user-a", {**profile, **invalid})

    def test_profile_gate_on_api(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("server.authenticated_subject", return_value="user-a"):
                for path in ("/api/facilities", "/api/visits"):
                    connection = HTTPConnection("127.0.0.1", server.server_port)
                    connection.request("GET", path)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 403)
                    response.read()
                    connection.close()
                user_records.save_profile("user-a", {"universityId": next(iter(user_records.UNIVERSITIES)),
                                                     "grade": "1", "gender": "prefer_not_to_say"})
                connection = HTTPConnection("127.0.0.1", server.server_port)
                connection.request("GET", "/api/visits")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
                connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_invalid_times_rejected(self):
        with self.assertRaises(ValueError):
            user_records.save_record("user-a", {**self.record, "leaveAt": "2026-10-11T00:00:00Z"})

    def test_token_signature_expiry_issuer_and_audience(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        claims = {"sub": "user-a", "iss": "https://tenant.auth0.com/", "aud": "clinic-api",
                  "exp": int(time.time()) + 60}
        jwks = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key()))
        with patch.multiple(user_records, DOMAIN="tenant.auth0.com", CLIENT_ID="client",
                            AUDIENCE="clinic-api", JWKS_CLIENT=jwks):
            token = jwt.encode(claims, key, algorithm="RS256")
            self.assertEqual(user_records.authenticated_subject(f"Bearer {token}"), "user-a")
            for replacement in ({"exp": 1}, {"aud": "other-api"}, {"iss": "https://other/"}):
                token = jwt.encode({**claims, **replacement}, key, algorithm="RS256")
                with self.assertRaises(jwt.InvalidTokenError):
                    user_records.authenticated_subject(f"Bearer {token}")
            other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            token = jwt.encode(claims, other_key, algorithm="RS256")
            with self.assertRaises(jwt.InvalidTokenError):
                user_records.authenticated_subject(f"Bearer {token}")

    def test_rejects_opaque_encrypted_and_wrong_algorithm_tokens(self):
        with patch.multiple(user_records, DOMAIN="tenant.auth0.com", CLIENT_ID="client", AUDIENCE="api"):
            for token in ("opaque-token", "one.two.three.four.five"):
                with self.assertRaises(jwt.DecodeError):
                    user_records.authenticated_subject(f"Bearer {token}")
            token = jwt.encode({"sub": "test"}, "test-key-with-at-least-thirty-two-characters", algorithm="HS256")
            with self.assertRaises(jwt.InvalidAlgorithmError):
                user_records.authenticated_subject(f"Bearer {token}")

    def test_small_clock_skew_allowed_but_invalid_tokens_still_rejected(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = int(time.time())
        claims = {"sub": "user-a", "iss": "https://tenant.auth0.com/", "aud": "clinic-api",
                  "iat": now + 20, "nbf": now + 20, "exp": now + 3600}
        jwks = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key()))
        with patch.multiple(user_records, DOMAIN="tenant.auth0.com", CLIENT_ID="client",
                            AUDIENCE="clinic-api", JWKS_CLIENT=jwks):
            token = jwt.encode(claims, key, algorithm="RS256")
            self.assertEqual(user_records.authenticated_subject(f"Bearer {token}"), "user-a")
            for replacement in ({"iat": now + 120}, {"nbf": now + 120}, {"exp": now - 120},
                                {"aud": "wrong-api"}, {"iss": "https://wrong-tenant/"}):
                with self.subTest(replacement=replacement), self.assertRaises(jwt.InvalidTokenError):
                    token = jwt.encode({**claims, **replacement}, key, algorithm="RS256")
                    user_records.authenticated_subject(f"Bearer {token}")

    def test_http_rejects_unauthenticated_and_private_files(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.multiple(user_records, DOMAIN="tenant.auth0.com", CLIENT_ID="client", AUDIENCE="api"):
                for path, expected in (("/api/visits", 401), ("/data/user-records.sqlite3", 404),
                                       ("/.env", 404), ("/user_records.py", 404), ("/", 200)):
                    connection = HTTPConnection("127.0.0.1", server.server_port)
                    connection.request("GET", path)
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected, path)
                    response.read()
                    connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_app_files_revalidate_cached_responses(self):
        app = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        thread = threading.Thread(target=app.serve_forever, daemon=True)
        thread.start()
        try:
            for path in ("/", "/index.html", "/app.js?v=old", "/styles.css", "/ui.generated.css"):
                connection = HTTPConnection("127.0.0.1", app.server_port)
                connection.request("GET", path)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Cache-Control"), "no-cache")
                modified = response.getheader("Last-Modified")
                response.read()
                connection.request("GET", path, headers={"If-Modified-Since": modified})
                response = connection.getresponse()
                self.assertEqual(response.status, 304)
                self.assertEqual(response.getheader("Cache-Control"), "no-cache")
                response.read()
                connection.close()
        finally:
            app.shutdown()
            app.server_close()
            thread.join()

    def test_key_network_failure_is_service_unavailable(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("server.authenticated_subject", side_effect=jwt.PyJWKClientConnectionError("offline")):
                connection = HTTPConnection("127.0.0.1", server.server_port)
                connection.request("GET", "/api/visits")
                response = connection.getresponse()
                self.assertEqual(response.status, 503)
                self.assertIn(b"auth_key_unavailable", response.read())
                connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
