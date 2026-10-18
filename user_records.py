import json
import os
import sqlite3
from uuid import uuid4
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import jwt
from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"), override=False)

DOMAIN = os.environ.get("AUTH0_DOMAIN", "").strip()
CLIENT_ID = os.environ.get("AUTH0_CLIENT_ID", "").strip()
AUDIENCE = os.environ.get("AUTH0_AUDIENCE", "").strip()
RECORDS_DATABASE = Path(os.environ.get(
    "RECORDS_DATABASE", str(Path(__file__).parent / "data" / "user-records.sqlite3")
))
JWKS_CLIENT = jwt.PyJWKClient(f"https://{DOMAIN}/.well-known/jwks.json") if DOMAIN else None
UNIVERSITY_DATA = json.loads((Path(__file__).parent / "data" / "universities.json").read_text(encoding="utf-8"))
UNIVERSITIES = {item["id"]: item for item in UNIVERSITY_DATA["universities"]}
GRADES = {"1", "2", "3", "4", "5", "6", "master1", "master2", "doctor1", "doctor2", "doctor3", "other"}
GENDERS = {"female", "male", "other", "prefer_not_to_say"}
MIYAZAKI_UNIVERSITY_ID = "F145110111523"
REVIEW_FIELDS = ("showGrade", "showReservation", "showDuration", "showFee")


def auth_config():
    return {"domain": DOMAIN, "clientId": CLIENT_ID, "audience": AUDIENCE,
            "configured": bool(DOMAIN and CLIENT_ID and AUDIENCE)}


def authenticated_subject(authorization):
    if not auth_config()["configured"]:
        raise RuntimeError("Auth0 is not configured")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise jwt.InvalidTokenError("Missing bearer token")
    if len(token.split(".")) != 3:
        raise jwt.DecodeError("Expected a signed JWT access token")
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "RS256":
        raise jwt.InvalidAlgorithmError("Expected RS256")
    key = JWKS_CLIENT.get_signing_key_from_jwt(token)
    claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=AUDIENCE, leeway=60,
                        issuer=f"https://{DOMAIN}/", options={"require": ["exp", "iss", "aud", "sub"]})
    subject = claims["sub"]
    if not isinstance(subject, str) or not subject:
        raise jwt.InvalidTokenError("Invalid subject")
    return subject


@contextmanager
def connect_records():
    RECORDS_DATABASE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(RECORDS_DATABASE, timeout=10)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS visits (
            user_id TEXT NOT NULL, visit_id TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY (user_id, visit_id)
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id TEXT PRIMARY KEY, payload TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            user_id TEXT NOT NULL, visit_id TEXT NOT NULL, hospital_id TEXT NOT NULL,
            payload TEXT NOT NULL, PRIMARY KEY (user_id, visit_id)
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS reviews_hospital ON reviews (hospital_id)")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def list_records(subject):
    with connect_records() as connection:
        rows = connection.execute("SELECT payload FROM visits WHERE user_id = ?", (subject,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def get_profile(subject):
    with connect_records() as connection:
        row = connection.execute("SELECT payload FROM profiles WHERE user_id = ?", (subject,)).fetchone()
    return json.loads(row[0]) if row else None


def save_profile(subject, value):
    if not isinstance(value, dict):
        raise ValueError("プロフィールの形式が正しくありません。")
    university_id = value.get("universityId")
    grade = value.get("grade")
    gender = value.get("gender")
    if not isinstance(university_id, str) or university_id not in UNIVERSITIES:
        raise ValueError("一覧から大学を選択してください。")
    if not isinstance(grade, str) or grade not in GRADES:
        raise ValueError("学年を選択してください。")
    if not isinstance(gender, str) or gender not in GENDERS:
        raise ValueError("性別または回答しないを選択してください。")
    profile = {"universityId": university_id, "universityName": UNIVERSITIES[university_id]["name"],
               "grade": grade, "gender": gender}
    with connect_records() as connection:
        connection.execute("INSERT INTO profiles (user_id, payload) VALUES (?, ?) "
                           "ON CONFLICT(user_id) DO UPDATE SET payload = excluded.payload",
                           (subject, json.dumps(profile, ensure_ascii=False)))
    return profile


def validate_record(value):
    if not isinstance(value, dict):
        raise ValueError("記録の形式が正しくありません。")
    result = {}
    for field in ("id", "hospitalId", "hospitalName", "department", "arrivalAt", "leaveAt", "plannedAt"):
        text = value.get(field)
        if not isinstance(text, str) or not text or len(text) > 300:
            raise ValueError("記録の必須項目が正しくありません。")
        result[field] = text
    try:
        arrival = datetime.fromisoformat(result["arrivalAt"].replace("Z", "+00:00"))
        leave = datetime.fromisoformat(result["leaveAt"].replace("Z", "+00:00"))
        if arrival.tzinfo is None or leave.tzinfo is None or leave < arrival:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("到着・終了日時が正しくありません。") from None
    result["stayMinutes"] = max(1, round((leave - arrival).total_seconds() / 60))
    for field, allowed in (
        ("reservationStatus", {"未入力", "予約あり", "予約なし"}),
        ("waitingImpression", {"未入力", "スムーズ", "普通", "待った"}),
    ):
        if value.get(field) not in allowed:
            raise ValueError("予約・待ち時間の値が正しくありません。")
        result[field] = value[field]
    fee = value.get("feeAmount", "")
    try:
        if fee != "" and (not str(fee).isdigit() or int(fee) > 10000000):
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("費用が正しくありません。") from None
    result.update(feeAmount=str(fee), status="completed", userConfirmed=True)
    note = value.get("note", "")
    if not isinstance(note, str) or len(note) > 2000:
        raise ValueError("口コミは2000文字以内で入力してください。")
    result["note"] = note.strip()
    sharing = value.get("reviewSharing", {})
    if not isinstance(sharing, dict):
        raise ValueError("口コミの公開設定が正しくありません。")
    result["reviewSharing"] = {}
    for field in ("published", *REVIEW_FIELDS):
        selected = sharing.get(field, field != "published")
        if not isinstance(selected, bool):
            raise ValueError("口コミの公開設定が正しくありません。")
        result["reviewSharing"][field] = selected
    if result["reviewSharing"]["published"] and not result["note"]:
        raise ValueError("公開する口コミの文章を入力してください。")
    return result


def grade_band(grade):
    if grade in {"1", "2"}:
        return "学部1〜2年"
    if grade in {"3", "4"}:
        return "学部3〜4年"
    if grade in {"5", "6"}:
        return "学部5〜6年"
    return "大学院生" if grade.startswith(("master", "doctor")) else "学生"


def save_record(subject, value):
    record = validate_record(value)
    with connect_records() as connection:
        sharing = record["reviewSharing"]
        if sharing["published"]:
            profile_row = connection.execute("SELECT payload FROM profiles WHERE user_id = ?", (subject,)).fetchone()
            profile = json.loads(profile_row[0]) if profile_row else {}
            if profile.get("universityId") != MIYAZAKI_UNIVERSITY_ID:
                raise ValueError("口コミの公開は宮崎大学の登録者が利用できます。")
            previous = connection.execute("SELECT payload FROM reviews WHERE user_id = ? AND visit_id = ?",
                                          (subject, record["id"])).fetchone()
            public = {"id": json.loads(previous[0])["id"] if previous else str(uuid4()),
                      "hospitalId": record["hospitalId"], "note": record["note"]}
            # Only explicitly selected, non-identifying fields enter the public projection.
            if sharing["showGrade"]:
                public["gradeBand"] = grade_band(profile["grade"])
            for flag, field in (("showReservation", "reservationStatus"), ("showDuration", "stayMinutes"),
                                ("showFee", "feeAmount")):
                if sharing[flag]:
                    public[field] = record[field]
            connection.execute("""
                INSERT INTO reviews (user_id, visit_id, hospital_id, payload) VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, visit_id) DO UPDATE SET hospital_id = excluded.hospital_id, payload = excluded.payload
            """, (subject, record["id"], record["hospitalId"], json.dumps(public, ensure_ascii=False)))
        else:
            connection.execute("DELETE FROM reviews WHERE user_id = ? AND visit_id = ?", (subject, record["id"]))
        connection.execute("""
            INSERT INTO visits (user_id, visit_id, payload) VALUES (?, ?, ?)
            ON CONFLICT(user_id, visit_id) DO UPDATE SET payload = excluded.payload
        """, (subject, record["id"], json.dumps(record, ensure_ascii=False)))
    return record


def list_reviews(subject, hospital_id):
    with connect_records() as connection:
        rows = connection.execute("""
            SELECT r.user_id, r.payload FROM reviews r JOIN profiles p ON p.user_id = r.user_id
            WHERE r.hospital_id = ? AND json_extract(p.payload, '$.universityId') = ?
            ORDER BY r.rowid DESC LIMIT 50
        """, (hospital_id, MIYAZAKI_UNIVERSITY_ID)).fetchall()
    return [{**json.loads(payload), "isOwnRecord": owner == subject} for owner, payload in rows]


def unpublish_review(subject, visit_id):
    with connect_records() as connection:
        row = connection.execute("SELECT payload FROM visits WHERE user_id = ? AND visit_id = ?",
                                 (subject, visit_id)).fetchone()
        if not row:
            raise ValueError("受診記録が見つかりません。")
        record = json.loads(row[0])
        record["reviewSharing"] = {**record.get("reviewSharing", {}), "published": False}
        connection.execute("DELETE FROM reviews WHERE user_id = ? AND visit_id = ?", (subject, visit_id))
        connection.execute("UPDATE visits SET payload = ? WHERE user_id = ? AND visit_id = ?",
                           (json.dumps(record, ensure_ascii=False), subject, visit_id))
    return record
