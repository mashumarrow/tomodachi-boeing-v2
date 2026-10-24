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
from io import StringIO, BytesIO
from urllib.error import URLError
from urllib.parse import urlencode
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

    def test_hospital_stay_average_uses_saved_times_and_updates_without_duplicates(self):
        self.miyazaki_profile()
        user_records.save_record("user-a", {**self.record, "stayMinutes": 999})
        second = {**self.record, "id": "visit-2", "leaveAt": "2026-10-12T00:46:00Z"}
        user_records.save_record("user-a", second)
        user_records.save_record("user-a", second)
        user_records.save_record("user-a", {**self.record, "id": "other-hospital", "hospitalId": "clinic:2"})
        self.assertEqual(user_records.hospital_stay_averages("user-a", ["clinic:1", "missing"]), {
            "clinic:1": {"averageStayMinutes": 36, "staySampleCount": 2}})
        user_records.save_record("user-a", {**second, "leaveAt": "2026-10-12T00:55:00Z"})
        self.assertEqual(user_records.hospital_stay_averages("user-a", ["clinic:1"]), {
            "clinic:1": {"averageStayMinutes": 40, "staySampleCount": 2}})
        self.assertEqual(user_records.hospital_stay_averages("user-a", []), {})

    def test_hospital_stay_average_respects_publication_and_duration_visibility(self):
        self.miyazaki_profile("user-a")
        self.miyazaki_profile("user-b")
        self.miyazaki_profile("user-c")
        user_records.save_record("user-a", self.published_record())
        user_records.save_record("user-b", self.published_record(leaveAt="2026-10-12T01:15:00Z"))
        user_records.save_record("user-b", self.published_record(
            id="hidden-duration", leaveAt="2026-10-12T01:45:00Z",
            reviewSharing={"published": True, "showDuration": False}))
        user_records.save_record("user-c", {**self.record, "leaveAt": "2026-10-12T02:25:00Z"})
        expected = {"clinic:1": {"averageStayMinutes": 50, "staySampleCount": 2}}
        self.assertEqual(user_records.hospital_stay_averages("user-a", ["clinic:1"]), expected)
        self.assertEqual(user_records.hospital_stay_averages("unknown", ["clinic:1"]), {})
        user_records.unpublish_review("user-b", "visit-1")
        self.assertEqual(user_records.hospital_stay_averages("user-a", ["clinic:1"]), {
            "clinic:1": {"averageStayMinutes": 35, "staySampleCount": 1}})
        self.assertEqual(user_records.hospital_stay_averages("user-b", ["clinic:1"]), {
            "clinic:1": {"averageStayMinutes": 65, "staySampleCount": 3}})
        other_school = next(code for code in user_records.UNIVERSITIES if code != user_records.MIYAZAKI_UNIVERSITY_ID)
        self.legacy_profile("user-a", {"universityId": other_school, "grade": "4",
                                             "gender": "female", "nickname": "ひなた"})
        self.assertEqual(user_records.hospital_stay_averages("user-c", ["clinic:1"]), {
            "clinic:1": {"averageStayMinutes": 135, "staySampleCount": 1}})
        self.assertEqual(user_records.hospital_stay_averages("user-a", ["clinic:1"]), {
            "clinic:1": {"averageStayMinutes": 35, "staySampleCount": 1}})

    def test_hospital_stay_average_ignores_incomplete_or_invalid_legacy_durations(self):
        user_records.save_record("user-a", self.record)
        with user_records.connect_records() as connection:
            for index, replacement in enumerate((
                {"status": "planned"}, {"status": "measuring"}, {"stayMinutes": None},
                {"stayMinutes": -5}, {"stayMinutes": 0}, {"stayMinutes": "35"}, {"stayMinutes": True},
            )):
                payload = {**self.record, "status": "completed", "stayMinutes": 100, **replacement}
                connection.execute("INSERT INTO visits VALUES (?, ?, ?)",
                                   ("user-a", f"legacy-{index}", json.dumps(payload)))
        self.assertEqual(user_records.hospital_stay_averages("user-a", ["clinic:1"]), {
            "clinic:1": {"averageStayMinutes": 35, "staySampleCount": 1}})

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

    def test_hospital_fee_average_only_uses_visible_published_fees(self):
        self.miyazaki_profile("user-a")
        self.miyazaki_profile("user-b")
        user_records.save_record("user-a", {**self.record, "feeAmount": "9000"})
        user_records.save_record("user-a", self.published_record(id="public-a", feeAmount="1500"))
        public_b = self.published_record(feeAmount="2401")
        user_records.save_record("user-b", public_b)
        user_records.save_record("user-b", public_b)
        # Existing reviews without a fee still must not affect the average.
        with user_records.connect_records() as connection:
            connection.execute("INSERT INTO reviews VALUES (?, ?, ?, ?)",
                               ("user-b", "missing-fee", "clinic:1", json.dumps({"hospitalId": "clinic:1", "feeAmount": ""})))
        user_records.save_record("user-b", self.published_record(
            id="hidden-fee", feeAmount="8000", reviewSharing={"published": True, "showFee": False}))
        user_records.save_record("user-b", self.published_record(id="other-hospital", hospitalId="clinic:2", feeAmount="5000"))
        self.assertEqual(user_records.hospital_fee_averages("user-a", ["clinic:1", "missing"]), {
            "clinic:1": {"averageFeeAmount": 1951, "feeSampleCount": 2}})
        self.assertEqual(user_records.hospital_fee_averages("user-a", []), {})
        self.assertEqual(user_records.hospital_fee_averages("unknown", ["clinic:1"]), {})
        user_records.save_record("user-b", {**public_b, "feeAmount": "2500"})
        self.assertEqual(user_records.hospital_fee_averages("user-a", ["clinic:1"]), {
            "clinic:1": {"averageFeeAmount": 2000, "feeSampleCount": 2}})
        user_records.unpublish_review("user-b", "visit-1")
        self.assertEqual(user_records.hospital_fee_averages("user-a", ["clinic:1"]), {
            "clinic:1": {"averageFeeAmount": 1500, "feeSampleCount": 1}})
        other_school = next(code for code in user_records.UNIVERSITIES if code != user_records.MIYAZAKI_UNIVERSITY_ID)
        self.legacy_profile("user-a", {"universityId": other_school, "grade": "4",
                                             "gender": "female", "nickname": "ひなた"})
        self.assertEqual(user_records.hospital_fee_averages("user-a", ["clinic:1"]), {})
        self.assertEqual(user_records.hospital_fee_averages("user-b", ["clinic:1"]), {})

    def test_hospital_fee_average_includes_zero_and_ignores_invalid_legacy_values(self):
        self.miyazaki_profile()
        user_records.save_record("user-a", self.published_record(feeAmount="0"))
        self.assertEqual(user_records.hospital_fee_averages("user-a", ["clinic:1"]), {
            "clinic:1": {"averageFeeAmount": 0, "feeSampleCount": 1}})
        user_records.save_record("user-a", self.published_record(id="full-width-fee", feeAmount="１０００"))
        with user_records.connect_records() as connection:
            for index, fee in enumerate((None, "", " ", True, [], -100, 1.5, "unknown", "1200abc", "²", "10000001")):
                payload = {"hospitalId": "clinic:1", "feeAmount": fee}
                connection.execute("INSERT INTO reviews VALUES (?, ?, ?, ?)",
                                   ("user-a", f"legacy-{index}", "clinic:1", json.dumps(payload)))
        self.assertEqual(user_records.hospital_fee_averages("user-a", ["clinic:1"]), {
            "clinic:1": {"averageFeeAmount": 500, "feeSampleCount": 2}})

    def test_hospital_fee_average_uses_more_than_the_latest_fifty_reviews(self):
        self.miyazaki_profile()
        for index in range(51):
            user_records.save_record("user-a", self.published_record(id=f"visit-{index}", feeAmount=str(index)))
        self.assertEqual(len(user_records.list_reviews("user-a", "clinic:1")), 50)
        self.assertEqual(user_records.hospital_fee_averages("user-a", ["clinic:1"]), {
            "clinic:1": {"averageFeeAmount": 25, "feeSampleCount": 51}})

    def test_fee_is_required_and_accepts_zero(self):
        for published in (False, True):
            value = self.published_record(reviewSharing={"published": published})
            for fee in (None, "", " ", True, -1, 1.5, "10000001"):
                with self.subTest(published=published, fee=fee), self.assertRaises(ValueError):
                    user_records.validate_record({**value, "feeAmount": fee})
            del value["feeAmount"]
            with self.assertRaisesRegex(ValueError, "費用を入力"):
                user_records.validate_record(value)
            for fee in (0, "0", 10000000):
                self.assertEqual(user_records.validate_record({**value, "feeAmount": fee})["feeAmount"], str(fee))

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
                                                   "grade": grade, "gender": "female", "nickname": "ひなた"})

    def legacy_profile(self, subject, value):
        profile = {**value, "universityName": user_records.UNIVERSITIES[value["universityId"]]["name"]}
        with user_records.connect_records() as connection:
            connection.execute("INSERT INTO profiles VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET payload = excluded.payload",
                               (subject, json.dumps(profile)))
        return profile

    def published_record(self, **overrides):
        return {**self.record, "note": "説明が丁寧でした。", "reviewSharing": {"published": True}, **overrides}

    def test_reviews_are_private_until_explicitly_published(self):
        self.miyazaki_profile()
        user_records.save_record("user-a", {**self.record, "note": "自分用のメモ"})
        self.assertEqual(user_records.list_reviews("user-b", "clinic:1"), [])
        user_records.save_record("user-a", self.published_record(gradeLabel="偽の学年", gender="female"))
        reviews = user_records.list_reviews("user-b", "clinic:1")
        self.assertEqual(len(reviews), 1)
        public = reviews[0]
        self.assertEqual(public["gradeLabel"], "学部4年")
        self.assertEqual(public["stayMinutes"], 35)
        self.assertEqual(public["feeAmount"], "1200")
        self.assertFalse(public["isOwnRecord"])
        self.assertNotEqual(public["id"], self.record["id"])
        self.assertEqual(set(public), {"id", "hospitalId", "note", "gradeLabel", "stayMinutes", "feeAmount",
                                       "reservationStatus", "isOwnRecord", "arrivalAt", "leaveAt"})
        user_records.save_record("user-a", self.published_record())
        self.assertEqual(len(user_records.list_reviews("user-b", "clinic:1")), 1)
        self.assertEqual(user_records.list_reviews("user-b", "clinic:2"), [])
        self.assertTrue(user_records.list_reviews("user-a", "clinic:1")[0]["isOwnRecord"])

    def test_review_field_selection_and_withdrawal_preserve_private_record(self):
        self.miyazaki_profile()
        sharing = {"published": True, **{field: False for field in user_records.REVIEW_FIELDS}}
        user_records.save_record("user-a", self.published_record(reviewSharing=sharing))
        self.assertEqual(set(user_records.list_reviews("user-b", "clinic:1")[0]),
                         {"id", "hospitalId", "note", "isOwnRecord", "arrivalAt", "leaveAt"})
        with self.assertRaises(ValueError):
            user_records.unpublish_review("user-b", "visit-1")
        self.assertEqual(len(user_records.list_reviews("user-b", "clinic:1")), 1)
        record = user_records.unpublish_review("user-a", "visit-1")
        self.assertFalse(record["reviewSharing"]["published"])
        self.assertEqual(record["note"], "説明が丁寧でした。")
        self.assertEqual(record["arrivalAt"], self.record["arrivalAt"])
        self.assertEqual(user_records.list_reviews("user-b", "clinic:1"), [])
        self.assertEqual(len(user_records.list_records("user-a")), 1)

    def test_review_grade_uses_publication_snapshot_and_preserves_legacy_band(self):
        self.miyazaki_profile("user-a", "3")
        user_records.save_record("user-a", self.structured_review(gradeLabel="学部6年"))
        self.miyazaki_profile("user-a", "4")
        public = user_records.list_reviews("user-b", "clinic:1")[0]
        self.assertEqual(public["gradeLabel"], "学部3年")
        self.assertNotIn("gradeBand", public)
        self.assertEqual(public["arrivalAt"], self.record["arrivalAt"])
        self.assertEqual(public["leaveAt"], self.record["leaveAt"])
        legacy = {"hospitalId": "clinic:1", "gradeBand": "学部3〜4年", "note": "以前の口コミ"}
        with user_records.connect_records() as connection:
            connection.execute("INSERT INTO reviews VALUES (?, ?, ?, ?)",
                               ("user-a", "legacy-grade", "clinic:1", json.dumps(legacy)))
        legacy_public = next(review for review in user_records.list_reviews("user-b", "clinic:1")
                             if review.get("note") == "以前の口コミ")
        self.assertEqual(legacy_public["gradeBand"], "学部3〜4年")
        self.assertNotIn("gradeLabel", legacy_public)

    def test_precise_visit_times_are_included_for_all_public_reviews(self):
        self.miyazaki_profile()
        value = self.structured_review()
        for sharing in ({"published": True}, {"published": True, "showVisitTimes": False},
                        {"published": True, "showVisitTimes": True}):
            saved = user_records.save_record("user-a", {**value, "reviewSharing": sharing})
            self.assertTrue(saved["reviewSharing"]["showVisitTimes"])
            public = user_records.list_reviews("user-b", "clinic:1")[0]
            self.assertEqual(public["visitedMonth"], "2026-10")
            self.assertEqual(public["arrivalAt"], value["arrivalAt"])
            self.assertEqual(public["leaveAt"], value["leaveAt"])
        with self.assertRaises(ValueError):
            user_records.validate_record({**value, "reviewSharing": {"published": True, "showVisitTimes": "true"}})
        user_records.save_record("user-a", {**value, "reviewSharing": {"published": False}})
        self.assertEqual(user_records.list_reviews("user-b", "clinic:1"), [])
        self.assertEqual(user_records.list_records("user-a")[0]["arrivalAt"], value["arrivalAt"])

    def test_legacy_public_reviews_use_only_the_matching_visits_times(self):
        self.miyazaki_profile("user-a")
        self.miyazaki_profile("user-b")
        user_records.save_record("user-a", self.structured_review())
        user_records.save_record("user-b", self.structured_review(arrivalAt="2026-10-13T00:10:00Z",
                                                                  leaveAt="2026-10-13T00:45:00Z"))
        user_records.save_record("user-a", {**self.record, "id": "private"})
        with user_records.connect_records() as connection:
            rows = connection.execute("SELECT user_id, visit_id, payload FROM reviews").fetchall()
            for owner, visit_id, payload in rows:
                public = json.loads(payload)
                public.pop("arrivalAt")
                public.pop("leaveAt")
                connection.execute("UPDATE reviews SET payload = ? WHERE user_id = ? AND visit_id = ?",
                                   (json.dumps(public), owner, visit_id))
        reviews = user_records.list_reviews("user-a", "clinic:1")
        self.assertEqual(len(reviews), 2)
        own = next(review for review in reviews if review["isOwnRecord"])
        other = next(review for review in reviews if not review["isOwnRecord"])
        self.assertEqual(own["arrivalAt"], self.record["arrivalAt"])
        self.assertEqual(other["arrivalAt"], "2026-10-13T00:10:00Z")
        self.assertNotIn("user_id", own)
        self.assertNotIn("visit_id", own)
        user_records.unpublish_review("user-a", self.record["id"])
        self.assertEqual(len(user_records.list_reviews("user-a", "clinic:1")), 1)

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
        self.legacy_profile("user-a", {"universityId": other_school, "grade": "4", "gender": "female", "nickname": "ひなた"})
        self.assertEqual(user_records.list_reviews("user-b", "clinic:1"), [])
        with self.assertRaises(ValueError):
            user_records.save_record("user-a", self.published_record())
        for grade, expected in (("1", "学部1年"), ("3", "学部3年"), ("6", "学部6年"),
                                ("master1", "修士1年"), ("doctor3", "博士3年"), ("other", "学生")):
            self.assertEqual(user_records.grade_label(grade), expected)

    def test_review_api_authentication_and_publication_cannot_be_withdrawn(self):
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
                self.assertEqual(data["reviews"][0]["arrivalAt"], self.record["arrivalAt"])
                self.assertEqual(request("DELETE", "/api/reviews?visitId=visit-1")[0], 405)
            with patch("server.authenticated_subject", return_value="user-a"):
                self.assertEqual(request("DELETE", "/api/reviews?visitId=visit-1")[0], 405)
                self.assertEqual(len(request("GET", "/api/reviews?hospitalId=clinic:1")[1]["reviews"]), 1)
            other_school = next(code for code in user_records.UNIVERSITIES if code != user_records.MIYAZAKI_UNIVERSITY_ID)
            self.legacy_profile("user-b", {"universityId": other_school, "grade": "2", "gender": "female", "nickname": "ひなた"})
            with patch("server.authenticated_subject", return_value="user-b"):
                self.assertEqual(request("GET", "/api/reviews?hospitalId=clinic:1")[0], 403)
        finally:
            app.shutdown()
            app.server_close()
            thread.join()

    def structured_review(self, **overrides):
        return {**self.published_record(), "reviewVersion": 2, "note": "", "nickname": "ひなた", "visitType": "初診",
                "waitingMinutes": "20", "positivePoints": ["説明が分かりやすい"],
                "sceneText": "薬の使い方を紙に書いてくれた", "adviceText": "支払いは現金だった", **overrides}

    def test_publish_all_reviews_includes_private_and_withdrawn_history_without_duplicates(self):
        self.miyazaki_profile("user-a")
        self.miyazaki_profile("user-b", "2")
        private = self.structured_review(reviewSharing={"published": False, "showFee": False},
                                         universityEmailVerified=True, email="private@example.com")
        user_records.save_record("user-a", private)
        user_records.save_record("user-b", self.structured_review())
        user_records.unpublish_review("user-b", self.record["id"])
        user_records.save_record("user-a", self.structured_review(id="existing"), verified_email_university="doshisha")
        original = next(review for review in user_records.list_reviews("user-a", "clinic:1")
                        if review["universityEmailVerified"])
        self.assertEqual(user_records.publish_all_reviews("user-a"), 1)
        self.assertFalse(user_records.list_records("user-b")[0]["reviewSharing"]["published"])
        self.assertEqual(user_records.publish_all_reviews(), 1)
        self.assertEqual(user_records.publish_all_reviews(), 0)
        reviews = user_records.list_reviews("user-a", "clinic:1")
        self.assertEqual(len(reviews), 3)
        migrated = next(review for review in reviews if review["isOwnRecord"] and review["id"] != original["id"])
        self.assertEqual(migrated["arrivalAt"], self.record["arrivalAt"])
        self.assertEqual(migrated["sceneText"], private["sceneText"])
        self.assertFalse(migrated["universityEmailVerified"])
        self.assertNotIn("feeAmount", migrated)
        self.assertNotIn("email", migrated)
        self.assertNotIn("user_id", migrated)
        self.assertEqual(next(review for review in reviews if review["id"] == original["id"]), original)
        self.assertEqual(len(user_records.list_records("user-a")), 2)
        self.assertTrue(all(record["reviewSharing"]["published"] for record in user_records.list_records("user-a")))

    def test_publish_history_handles_legacy_fields_and_skips_unfinished_or_ineligible_records(self):
        self.miyazaki_profile()
        legacy = user_records.save_record("user-a", self.record)
        legacy.update(feeAmount="", note="以前の記録の文章", email="private@example.com")
        unfinished = {**legacy, "id": "unfinished", "status": "measuring", "leaveAt": None}
        invalid = {**legacy, "id": "invalid", "leaveAt": "not-a-time"}
        for record in (legacy, unfinished, invalid):
            with user_records.connect_records() as connection:
                connection.execute("INSERT OR REPLACE INTO visits VALUES (?, ?, ?)",
                                   ("user-a", record["id"], json.dumps(record)))
        user_records.save_record("no-profile", self.record)
        self.assertEqual(user_records.publish_all_reviews(), 1)
        review = user_records.list_reviews("user-b", "clinic:1")[0]
        self.assertEqual(review["note"], legacy["note"])
        self.assertEqual(review["nickname"], "ひなた")
        self.assertEqual(review["feeAmount"], "")
        self.assertNotIn("email", review)
        self.assertNotIn("universityEmailVerified", review)
        self.assertEqual(len(user_records.list_records("user-a")), 3)

    def test_review_nickname_comes_from_registered_profile(self):
        self.miyazaki_profile()
        record = user_records.save_record("user-a", self.structured_review(nickname="別の名前"))
        self.assertEqual(record["nickname"], "ひなた")
        self.assertEqual(user_records.list_reviews("user-b", "clinic:1")[0]["nickname"], "ひなた")
        profile = user_records.get_profile("user-a")
        del profile["nickname"]
        with user_records.connect_records() as connection:
            connection.execute("UPDATE profiles SET payload = ? WHERE user_id = ?", (json.dumps(profile), "user-a"))
        with self.assertRaisesRegex(ValueError, "ニックネーム"):
            user_records.save_record("user-a", self.structured_review())

    def test_structured_review_allows_optional_text_and_protects_identity(self):
        self.miyazaki_profile()
        value = self.structured_review()
        value.update(sceneText="", adviceText="", universityEmailVerified=True)
        user_records.save_record("user-a", value)
        public = user_records.list_reviews("user-b", "clinic:1")[0]
        self.assertEqual(public["nickname"], "ひなた")
        self.assertEqual(public["visitedMonth"], "2026-10")
        self.assertEqual(public["visitType"], "初診")
        self.assertEqual(public["waitingMinutes"], 20)
        self.assertEqual(public["sceneText"], "")
        self.assertFalse(public["universityEmailVerified"])
        self.assertEqual(public["arrivalAt"], value["arrivalAt"])
        self.assertNotIn("email", public)
        self.assertNotIn("user_id", public)
        user_records.save_record("user-a", value, verified_email_university="miyazaki")
        self.assertTrue(user_records.list_reviews("user-b", "clinic:1")[0]["universityEmailVerified"])
        self.assertEqual(user_records.visited_month("2026-09-30T15:00:00Z"), "2026-10")
        self.assertEqual(user_records.visited_month("2026-09-30T14:59:59Z"), "2026-09")

    def test_structured_review_validation(self):
        value = self.structured_review()
        for replacement in ({"nickname": "a" * 21}, {"visitType": []},
                            {"positivePoints": []}, {"positivePoints": ["偽の項目"]},
                            {"positivePoints": ["特になし・分からない", "質問しやすい"]},
                            {"waitingMinutes": True}, {"waitingMinutes": -1}, {"waitingMinutes": 1441},
                            {"sceneText": "a" * 2001}, {"adviceText": "a" * 1001}, {"reviewVersion": True}):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                user_records.validate_record({**value, **replacement})
        saved = user_records.validate_record({**value, "positivePoints": ["特になし・分からない"], "waitingMinutes": "0"})
        self.assertEqual(saved["waitingMinutes"], 0)

    def test_other_positive_point_can_be_saved_and_published_without_waiting_time(self):
        self.miyazaki_profile()
        value = self.structured_review(positivePoints=["その他", "質問しやすい"])
        del value["waitingMinutes"]
        saved = user_records.save_record("user-a", value)
        self.assertIsNone(saved["waitingMinutes"])
        public = user_records.list_reviews("user-b", "clinic:1")[0]
        self.assertEqual(public["positivePoints"], ["その他", "質問しやすい"])
        self.assertIsNone(public["waitingMinutes"])
        with self.assertRaises(ValueError):
            user_records.validate_record({**value, "positivePoints": ["その他", "特になし・分からない"]})

    def test_structured_review_requires_conditions_and_points_even_when_private(self):
        for published in (False, True):
            value = self.structured_review(reviewSharing={"published": published}, sceneText="", adviceText="")
            for field, invalid in (("visitType", "未入力"), ("reservationStatus", "未入力"), ("positivePoints", [])):
                with self.subTest(published=published, field=field):
                    with self.assertRaises(ValueError):
                        user_records.validate_record({**value, field: invalid})
                    missing = {key: item for key, item in value.items() if key != field}
                    with self.assertRaises(ValueError):
                        user_records.validate_record(missing)
            saved = user_records.validate_record({**value, "positivePoints": ["特になし・分からない"]})
            self.assertEqual(saved["sceneText"], "")
            self.assertEqual(saved["adviceText"], "")
            self.assertEqual(saved["positivePoints"], ["特になし・分からない"])

    def test_structured_review_requires_conditions_and_points_even_when_private(self):
        for published in (False, True):
            value = self.structured_review(reviewSharing={"published": published}, sceneText="", adviceText="")
            for field, invalid in (("visitType", "未入力"), ("reservationStatus", "未入力"), ("positivePoints", [])):
                with self.subTest(published=published, field=field):
                    with self.assertRaises(ValueError):
                        user_records.validate_record({**value, field: invalid})
                    missing = {key: item for key, item in value.items() if key != field}
                    with self.assertRaises(ValueError):
                        user_records.validate_record(missing)
            saved = user_records.validate_record({**value, "positivePoints": ["特になし・分からない"]})
            self.assertEqual(saved["sceneText"], "")
            self.assertEqual(saved["adviceText"], "")
            self.assertEqual(saved["positivePoints"], ["特になし・分からない"])

    def test_university_email_requires_auth0_verified_student_email_and_subject(self):
        identity = {"sub": "user-a", "email": "test@student.miyazaki-u.ac.jp", "email_verified": True}
        for changes, expected in (({}, "miyazaki"), ({"email_verified": False}, None), ({"email_verified": "true"}, None),
                                  ({"sub": "other-user"}, None), ({"email": "test@miyazaki-u.ac.jp"}, None),
                                  ({"email": "test@student.miyazaki-u.ac.jp.evil.example"}, None),
                                  ({"email": "@student.miyazaki-u.ac.jp"}, None), ({"email": None}, None)):
            with self.subTest(changes=changes), patch("user_records.urlopen", return_value=BytesIO(json.dumps({**identity, **changes}).encode())) as lookup:
                self.assertEqual(user_records.verified_email_university("user-a", "Bearer test-token"), expected)
                request = lookup.call_args.args[0]
                self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
                self.assertTrue(request.full_url.endswith("/userinfo"))

    def test_review_api_issues_email_badge_only_after_server_verification(self):
        self.miyazaki_profile()
        app = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        thread = threading.Thread(target=app.serve_forever, daemon=True)
        thread.start()
        def post(path, payload=None):
            connection = HTTPConnection("127.0.0.1", app.server_port)
            body = json.dumps(payload) if payload is not None else None
            connection.request("POST", path, body=body, headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"})
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result
        try:
            with patch("server.authenticated_subject", return_value="user-a"):
                with patch("server.verified_email_university", return_value="miyazaki") as verify, patch(
                    "server.email_verification_status", return_value={"universityEmailVerified": True,
                    "verifiedEmailUniversity": "miyazaki", "status": "verified"}):
                    self.assertEqual(post("/api/email-verification")[1]["universityEmailVerified"], True)
                    status, result = post("/api/visits", self.structured_review(reviewSharing={"published": False}))
                    self.assertEqual(status, 201)
                    self.assertTrue(result["visit"]["reviewSharing"]["published"])
                    verify.assert_called_with("user-a", "Bearer test-token")
                self.assertTrue(user_records.list_reviews("user-b", "clinic:1")[0]["universityEmailVerified"])
                with patch("server.verified_email_university", return_value="doshisha"), patch(
                    "server.email_verification_status", return_value={"universityEmailVerified": True,
                    "verifiedEmailUniversity": "doshisha", "status": "verified"}):
                    self.assertEqual(post("/api/email-verification")[1], {
                        "universityEmailVerified": True, "verifiedEmailUniversity": "doshisha",
                        "status": "verified", "updatedReviews": 1})
                    self.assertEqual(post("/api/visits", self.structured_review(verifiedEmailUniversity="miyazaki"))[0], 201)
                public = user_records.list_reviews("user-b", "clinic:1")[0]
                self.assertTrue(public["universityEmailVerified"])
                self.assertEqual(public["verifiedEmailUniversity"], "doshisha")
                self.assertNotIn("email", public)
                with patch("server.verified_email_university", return_value=None):
                    self.assertEqual(post("/api/visits", self.structured_review(
                        universityEmailVerified=True, verifiedEmailUniversity="doshisha"))[0], 201)
                public = user_records.list_reviews("user-b", "clinic:1")[0]
                self.assertFalse(public["universityEmailVerified"])
                self.assertNotIn("verifiedEmailUniversity", public)
                with patch("server.verified_email_university", side_effect=URLError("unavailable")), patch(
                    "server.email_verification_status", side_effect=URLError("unavailable")):
                    self.assertEqual(post("/api/email-verification")[0], 503)
                    self.assertEqual(post("/api/visits", self.structured_review())[0], 201)
                self.assertFalse(user_records.list_reviews("user-b", "clinic:1")[0]["universityEmailVerified"])
        finally:
            app.shutdown()
            app.server_close()
            thread.join()

    def test_email_verification_explains_missing_badges_without_revealing_email(self):
        identity = {"sub": "user-a", "email": "test@mail4.doshisha.ac.jp", "email_verified": True}
        for changes, status in (({}, "verified"), ({"email_verified": False}, "email_unverified"),
                                ({"email": "test@example.com"}, "unsupported_domain"),
                                ({"email": None}, "missing_email"), ({"sub": "user-b"}, "identity_mismatch")):
            with self.subTest(status=status), patch("user_records.urlopen", return_value=BytesIO(json.dumps({**identity, **changes}).encode())):
                result = user_records.email_verification_status("user-a", "Bearer token")
                self.assertEqual(result["status"], status)
                self.assertEqual(result["universityEmailVerified"], status == "verified")
                self.assertNotIn("email", result)
                if status != "verified":
                    self.assertIsNone(result["verifiedEmailUniversity"])

    def test_badge_sync_updates_only_owners_existing_public_reviews(self):
        self.miyazaki_profile("user-a")
        self.miyazaki_profile("user-b")
        value = self.structured_review(reviewSharing={"published": True, "showFee": False, "showVisitTimes": False})
        user_records.save_record("user-a", value)
        user_records.save_record("user-b", value)
        user_records.save_record("user-a", {**value, "id": "private", "reviewSharing": {"published": False}})
        user_records.save_record("user-a", {**value, "id": "withdrawn"})
        user_records.unpublish_review("user-a", "withdrawn")
        before = next(review for review in user_records.list_reviews("user-a", "clinic:1") if review["isOwnRecord"])
        self.assertEqual(user_records.sync_review_email_badges("user-a", None), 0)
        self.assertEqual(user_records.sync_review_email_badges("user-a", "doshisha"), 1)
        self.assertEqual(user_records.sync_review_email_badges("user-a", "doshisha"), 0)
        reviews = user_records.list_reviews("user-a", "clinic:1")
        self.assertEqual(len(reviews), 2)
        own = next(review for review in reviews if review["isOwnRecord"])
        other = next(review for review in reviews if not review["isOwnRecord"])
        self.assertTrue(own["universityEmailVerified"])
        self.assertEqual(own["verifiedEmailUniversity"], "doshisha")
        self.assertEqual({key: item for key, item in own.items() if key not in {"universityEmailVerified", "verifiedEmailUniversity"}},
                         {key: item for key, item in before.items() if key not in {"universityEmailVerified", "verifiedEmailUniversity"}})
        self.assertFalse(other["universityEmailVerified"])
        self.assertNotIn("feeAmount", own)
        self.assertEqual(own["arrivalAt"], value["arrivalAt"])
        self.assertEqual(len(user_records.list_records("user-a")), 3)

    def test_doshisha_email_verification_rejects_unverified_and_lookalike_addresses(self):
        for number in ("", "1", "2", "3", "4"):
            identity = {"sub": "user-a", "email": f"student@MAIL{number}.DOSHISHA.AC.JP", "email_verified": True}
            with self.subTest(number=number), patch("user_records.urlopen", return_value=BytesIO(json.dumps(identity).encode())):
                self.assertEqual(user_records.verified_email_university("user-a", "Bearer token"), "doshisha")
        identity = {"sub": "user-a", "email": "student@mail4.doshisha.ac.jp", "email_verified": True}
        for changes in ({"email_verified": False}, {"email_verified": "true"}, {"sub": "other-user"},
                        {"email": "student@mail4.doshisha.ac.jp.evil.example"}, {"email": "student@evilmail4.doshisha.ac.jp"},
                        {"email": "student@dwc.doshisha.ac.jp"}, {"email": "student@doshisha.ac.jp"},
                        {"email": "student@mail5.doshisha.ac.jp"}, {"email": "@mail4.doshisha.ac.jp"},
                        {"email": "student@@mail4.doshisha.ac.jp"}):
            with self.subTest(changes=changes), patch("user_records.urlopen", return_value=BytesIO(json.dumps({**identity, **changes}).encode())):
                self.assertIsNone(user_records.verified_email_university("user-a", "Bearer token"))

    def test_facility_search_only_returns_miyazaki_medical_facilities(self):
        database = Path(self.directory.name) / "facilities.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            connection.executescript("""
                CREATE TABLE facilities (
                    id TEXT, type TEXT, name TEXT, address TEXT, latitude REAL,
                    longitude REAL, website TEXT, open TEXT, median_wait INTEGER
                );
                CREATE TABLE facility_departments (facility_id TEXT, department TEXT);
            """)
            for facility_id, kind, address, latitude, longitude, department in (
                ("hospital", "hospital", "宮崎県宮崎市", 31.831, 131.412, "internal"),
                ("clinic", "clinic", "宮崎県宮崎市", 31.831, 131.412, "internal"),
                ("pharmacy", "pharmacy", "宮崎県宮崎市", 31.831, 131.412, "internal"),
                ("outside-prefecture", "hospital", "鹿児島県鹿児島市", 31.831, 131.412, "internal"),
                ("kyoto", "clinic", "京都府京都市", 35, 135, "internal"),
                ("distant", "clinic", "宮崎県延岡市", 32.58, 131.66, "internal"),
                ("eye", "clinic", "宮崎県宮崎市", 31.831, 131.412, "eye"),
                ("unknown-address", "hospital", "", 31.831, 131.412, "internal"),
            ):
                connection.execute("INSERT INTO facilities VALUES (?, ?, ?, ?, ?, ?, '', '', 30)",
                                   (facility_id, kind, facility_id, address, latitude, longitude))
                connection.execute("INSERT INTO facility_departments VALUES (?, ?)", (facility_id, department))
            connection.commit()
        app = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        thread = threading.Thread(target=app.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("server.DATABASE", database), patch("server.authenticated_subject", return_value="user-a"):
                user_records.save_profile("user-a", {"universityId": user_records.MIYAZAKI_UNIVERSITY_ID,
                                                     "grade": "1", "gender": "prefer_not_to_say", "nickname": "ひなた"})
                for suffix in ("", "&type=pharmacy", "&type=medical", "&" + urlencode({"prefecture": "京都府"})):
                    connection = HTTPConnection("127.0.0.1", app.server_port)
                    connection.request("GET", "/api/facilities?latitude=31.831&longitude=131.412&department=internal" + suffix)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    facilities = json.loads(response.read())["facilities"]
                    self.assertEqual({item["type"] for item in facilities}, {"hospital", "clinic"})
                    self.assertEqual({item["id"] for item in facilities}, {"hospital", "clinic"})
                    self.assertTrue(all(item["address"].startswith("宮崎県") for item in facilities))
                    self.assertTrue(all(item["averageStayMinutes"] is None and item["staySampleCount"] == 0
                                        for item in facilities))
                    self.assertTrue(all(item["averageFeeAmount"] is None and item["feeSampleCount"] == 0
                                        for item in facilities))
                    connection.close()
                connection = HTTPConnection("127.0.0.1", app.server_port)
                connection.request("GET", "/api/facilities?latitude=35&longitude=135&department=internal")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["facilities"], [])
                connection.close()
                self.miyazaki_profile("user-a")
                self.miyazaki_profile("user-b")
                user_records.save_record("user-a", {**self.record, "hospitalId": "clinic", "feeAmount": "9000"})
                user_records.save_record("user-b", self.published_record(
                    hospitalId="clinic", leaveAt="2026-10-12T01:15:00Z"))
                connection = HTTPConnection("127.0.0.1", app.server_port)
                connection.request("GET", "/api/facilities?latitude=31.831&longitude=131.412&department=internal&user_id=user-b")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                by_id = {item["id"]: item for item in json.loads(response.read())["facilities"]}
                self.assertEqual(by_id["clinic"]["averageStayMinutes"], 50)
                self.assertEqual(by_id["clinic"]["staySampleCount"], 2)
                self.assertEqual(by_id["clinic"]["averageFeeAmount"], 1200)
                self.assertEqual(by_id["clinic"]["feeSampleCount"], 1)
                self.assertIsNone(by_id["hospital"]["averageStayMinutes"])
                self.assertIsNone(by_id["hospital"]["averageFeeAmount"])
                self.assertEqual(by_id["hospital"]["medianWait"], 30)
                self.assertNotIn("arrivalAt", by_id["clinic"])
                self.assertNotIn("user_id", by_id["clinic"])
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

    def test_legacy_other_university_profile_requires_fixed_registration(self):
        self.legacy_profile("user-b", {"universityId": "F126310107564",
                                       "grade": "4", "gender": "prefer_not_to_say", "nickname": "テスト"})
        user_records.save_record("user-b", self.record)
        with self.assertRaises(ValueError):
            user_records.save_record("user-b", self.structured_review())
        app = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        thread = threading.Thread(target=app.serve_forever, daemon=True)
        thread.start()
        def get(path):
            connection = HTTPConnection("127.0.0.1", app.server_port)
            connection.request("GET", path)
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result
        try:
            with patch("server.authenticated_subject", return_value="user-b"):
                for path in ("/api/university-origin", "/api/reviews?hospitalId=clinic:1", "/api/facilities", "/api/visits"):
                    status, data = get(path)
                    self.assertEqual(status, 403)
                    self.assertEqual(data["code"], "miyazaki_required")
                self.assertEqual(get("/api/profile")[1]["profile"]["universityId"], "F126310107564")
                connection = HTTPConnection("127.0.0.1", app.server_port)
                connection.request("POST", "/api/profile", body=json.dumps({"nickname": "テスト", "grade": "4", "gender": "prefer_not_to_say"}))
                response = connection.getresponse()
                self.assertEqual(response.status, 201)
                profile = json.loads(response.read())["profile"]
                self.assertEqual(profile["universityId"], user_records.MIYAZAKI_UNIVERSITY_ID)
                self.assertEqual(profile["universityName"], "宮崎大学")
                connection.close()
                status, data = get("/api/university-origin")
                self.assertEqual(status, 200)
                self.assertIn("木花キャンパス", data["origin"]["label"])
                self.assertAlmostEqual(data["origin"]["latitude"], 31.8310233)
                self.assertEqual(len(user_records.list_records("user-b")), 1)
                self.assertEqual(get("/api/universities")[0], 404)
        finally:
            app.shutdown()
            app.server_close()
            thread.join()

    def test_profile_validation_and_ownership(self):
        university = user_records.MIYAZAKI_UNIVERSITY_ID
        profile = {"universityId": university, "grade": "4", "gender": "prefer_not_to_say", "nickname": "ひなた"}
        saved = user_records.save_profile("user-a", {**profile, "user_id": "user-b"})
        self.assertEqual(saved["universityName"], user_records.UNIVERSITIES[university]["name"])
        self.assertIsNone(user_records.get_profile("user-b"))
        self.assertEqual(user_records.get_profile("user-a")["grade"], "4")
        self.assertEqual(saved["nickname"], "ひなた")
        for invalid in ({"grade": "invalid"}, {"gender": "invalid"},
                        {"nickname": " "}, {"nickname": "a" * 21}, {"nickname": None}, {"nickname": 1}):
            with self.assertRaises(ValueError):
                user_records.save_profile("user-a", {**profile, **invalid})

    def test_registration_always_sets_miyazaki_without_university_input(self):
        value = {"nickname": "ひなた", "grade": "4", "gender": "prefer_not_to_say"}
        for university in (None, "F126310107564", "unknown", []):
            payload = value if university is None else {**value, "universityId": university, "universityName": "別の大学"}
            saved = user_records.save_profile("user-a", payload)
            self.assertEqual(saved["universityId"], user_records.MIYAZAKI_UNIVERSITY_ID)
            self.assertEqual(saved["universityName"], "宮崎大学")

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
                user_records.save_profile("user-a", {"universityId": user_records.MIYAZAKI_UNIVERSITY_ID,
                                                     "grade": "1", "gender": "prefer_not_to_say", "nickname": "ひなた"})
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
        for changes in ({"leaveAt": "2026-10-11T00:00:00Z"}, {"leaveAt": ""},
                        {"leaveAt": None}, {"arrivalAt": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                user_records.save_record("user-a", {**self.record, **changes})

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
                for method in ("GET", "HEAD"):
                    connection = HTTPConnection("127.0.0.1", server.server_port)
                    connection.request(method, "/assets/icons/log-out.svg")
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.getheader("Content-Type"), "image/svg+xml")
                    if method == "GET":
                        self.assertIn(b"<svg", response.read())
                    else:
                        self.assertEqual(response.read(), b"")
                    connection.close()
                for method in ("GET", "HEAD"):
                    connection = HTTPConnection("127.0.0.1", server.server_port)
                    connection.request(method, "/assets/universities/miyazaki-symbol.png")
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.getheader("Content-Type"), "image/png")
                    if method == "GET":
                        self.assertTrue(response.read().startswith(b"\x89PNG\r\n\x1a\n"))
                    else:
                        self.assertEqual(response.read(), b"")
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
