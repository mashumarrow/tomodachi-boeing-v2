import json
import math
import os
import sqlite3
from uuid import uuid4
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

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
REVIEW_FIELDS = ("showGrade", "showReservation", "showDuration", "showFee", "showVisitType", "showWaiting", "showVisitTimes")
POSITIVE_POINTS = ("説明が分かりやすい", "質問しやすい", "受付が丁寧", "プライバシーへの配慮", "その他", "特になし・分からない")


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


def verify_university_email(subject, authorization):
    request = Request(f"https://{DOMAIN}/userinfo", headers={"Authorization": authorization, "Accept": "application/json"})
    with urlopen(request, timeout=8) as response:
        data = json.loads(response.read(65536))
    if not isinstance(data, dict):
        return False
    email = data.get("email")
    return (data.get("sub") == subject and data.get("email_verified") is True
            and isinstance(email, str) and email.count("@") == 1
            and bool(email.partition("@")[0])
            and email.partition("@")[2].lower() == "student.miyazaki-u.ac.jp")


def visited_month(arrival_at):
    arrival = datetime.fromisoformat(arrival_at.replace("Z", "+00:00"))
    return arrival.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m")


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


def hospital_stay_averages(subject, hospital_ids):
    hospital_ids = list(dict.fromkeys(hospital_ids))
    if not hospital_ids:
        return {}
    placeholders = ",".join("?" for _ in hospital_ids)
    # Shared durations follow the same publication and university rules as reviews.
    with connect_records() as connection:
        rows = connection.execute(f"""
            SELECT json_extract(v.payload, '$.hospitalId') AS hospital_id,
                   AVG(json_extract(v.payload, '$.stayMinutes')), COUNT(*)
            FROM visits v
            WHERE json_extract(v.payload, '$.hospitalId') IN ({placeholders})
              AND json_extract(v.payload, '$.status') = 'completed'
              AND json_type(v.payload, '$.stayMinutes') IN ('integer', 'real')
              AND json_extract(v.payload, '$.stayMinutes') > 0
              AND (
                  v.user_id = ? OR (
                      EXISTS (
                          SELECT 1 FROM profiles viewer
                          WHERE viewer.user_id = ?
                            AND json_extract(viewer.payload, '$.universityId') = ?
                      )
                      AND EXISTS (
                          SELECT 1 FROM reviews r JOIN profiles author ON author.user_id = r.user_id
                          WHERE r.user_id = v.user_id AND r.visit_id = v.visit_id
                            AND r.hospital_id = json_extract(v.payload, '$.hospitalId')
                            AND json_type(r.payload, '$.stayMinutes') IN ('integer', 'real')
                            AND json_extract(author.payload, '$.universityId') = ?
                      )
                  )
              )
            GROUP BY hospital_id
        """, (*hospital_ids, subject, subject, MIYAZAKI_UNIVERSITY_ID, MIYAZAKI_UNIVERSITY_ID)).fetchall()
    return {hospital_id: {"averageStayMinutes": math.ceil(average), "staySampleCount": count}
            for hospital_id, average, count in rows}


def hospital_fee_averages(subject, hospital_ids):
    hospital_ids = list(dict.fromkeys(hospital_ids))
    if not hospital_ids:
        return {}
    placeholders = ",".join("?" for _ in hospital_ids)
    with connect_records() as connection:
        rows = connection.execute(f"""
            SELECT r.hospital_id, json_extract(r.payload, '$.feeAmount')
            FROM reviews r
            JOIN profiles author ON author.user_id = r.user_id
            JOIN profiles viewer ON viewer.user_id = ?
            WHERE r.hospital_id IN ({placeholders})
              AND json_extract(author.payload, '$.universityId') = ?
              AND json_extract(viewer.payload, '$.universityId') = ?
              AND json_type(r.payload, '$.feeAmount') IN ('integer', 'text')
        """, (subject, *hospital_ids, MIYAZAKI_UNIVERSITY_ID, MIYAZAKI_UNIVERSITY_ID)).fetchall()
    totals = {}
    for hospital_id, fee in rows:
        if not str(fee).isdigit():
            continue
        try:
            amount = int(fee)
        except ValueError:
            continue
        if not 0 <= amount <= 10000000:
            continue
        total = totals.setdefault(hospital_id, [0, 0])
        total[0] += amount
        total[1] += 1
    return {hospital_id: {"averageFeeAmount": math.floor(total / count + 0.5), "feeSampleCount": count}
            for hospital_id, (total, count) in totals.items()}


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
    nickname = value.get("nickname")
    if not isinstance(nickname, str) or not nickname.strip() or len(nickname) > 20:
        raise ValueError("ニックネームは1〜20文字で入力してください。")
    if not isinstance(university_id, str) or university_id not in UNIVERSITIES:
        raise ValueError("一覧から大学を選択してください。")
    if not isinstance(grade, str) or grade not in GRADES:
        raise ValueError("学年を選択してください。")
    if not isinstance(gender, str) or gender not in GENDERS:
        raise ValueError("性別または回答しないを選択してください。")
    profile = {"universityId": university_id, "universityName": UNIVERSITIES[university_id]["name"],
               "grade": grade, "gender": gender, "nickname": nickname.strip()}
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
    if fee is None or fee == "":
        raise ValueError("費用を入力してください。費用がかからなかった場合は0円と入力してください。")
    try:
        if not str(fee).isdigit() or int(fee) > 10000000:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("費用が正しくありません。") from None
    result.update(feeAmount=str(fee), status="completed", userConfirmed=True)
    note = value.get("note", "")
    if not isinstance(note, str) or len(note) > 2000:
        raise ValueError("口コミは2000文字以内で入力してください。")
    result["note"] = note.strip()
    version = value.get("reviewVersion", 1)
    if type(version) is not int or version not in (1, 2):
        raise ValueError("口コミの形式が正しくありません。")
    result["reviewVersion"] = version
    for field, label, limit in (("nickname", "ニックネーム", 20), ("sceneText", "そう感じた場面", 2000), ("adviceText", "次に行く学生へのメッセージ", 1000)):
        text = value.get(field, "")
        if not isinstance(text, str) or len(text) > limit:
            raise ValueError(f"{label}は{limit}文字以内で入力してください。")
        result[field] = text.strip()
    visit_type = value.get("visitType", "未入力")
    if not isinstance(visit_type, str) or visit_type not in {"未入力", "初診", "再診", "分からない"}:
        raise ValueError("初診・再診の選択が正しくありません。")
    result["visitType"] = visit_type
    waiting = value.get("waitingMinutes")
    if waiting is None or waiting == "":
        result["waitingMinutes"] = None
    elif (isinstance(waiting, (int, str)) and not isinstance(waiting, bool)
          and str(waiting).isdigit() and 0 <= int(waiting) <= 1440):
        result["waitingMinutes"] = int(waiting)
    else:
        raise ValueError("待ち時間は0〜1440分の整数で入力してください。")
    points = value.get("positivePoints", [])
    if (not isinstance(points, list) or len(points) > len(POSITIVE_POINTS)
            or any(not isinstance(point, str) or point not in POSITIVE_POINTS for point in points)):
        raise ValueError("よかった点の選択が正しくありません。")
    if POSITIVE_POINTS[-1] in points and len(points) > 1:
        raise ValueError("「特になし・分からない」は他の項目と同時に選択できません。")
    result["positivePoints"] = list(dict.fromkeys(points))
    if version == 2:
        if visit_type == "未入力":
            raise ValueError("初診・再診を選択してください。")
        if result["reservationStatus"] == "未入力":
            raise ValueError("予約の有無を選択してください。")
        if not points:
            raise ValueError("よかった点、または「特になし・分からない」を選択してください。")
    sharing = value.get("reviewSharing", {})
    if not isinstance(sharing, dict):
        raise ValueError("口コミの公開設定が正しくありません。")
    result["reviewSharing"] = {}
    for field in ("published", *REVIEW_FIELDS):
        selected = sharing.get(field, field not in {"published", "showVisitTimes"})
        if not isinstance(selected, bool):
            raise ValueError("口コミの公開設定が正しくありません。")
        result["reviewSharing"][field] = selected
    if result["reviewSharing"]["published"]:
        if version == 1 and not result["note"]:
            raise ValueError("公開する口コミの文章を入力してください。")
    return result


def grade_label(grade):
    if grade in {"1", "2", "3", "4", "5", "6"}:
        return f"学部{grade}年"
    if grade in {"master1", "master2"}:
        return f"修士{grade[-1]}年"
    if grade in {"doctor1", "doctor2", "doctor3"}:
        return f"博士{grade[-1]}年"
    return "学生"


def save_record(subject, value, *, university_email_verified=False):
    record = validate_record(value)
    with connect_records() as connection:
        sharing = record["reviewSharing"]
        if sharing["published"]:
            profile_row = connection.execute("SELECT payload FROM profiles WHERE user_id = ?", (subject,)).fetchone()
            profile = json.loads(profile_row[0]) if profile_row else {}
            if profile.get("universityId") != MIYAZAKI_UNIVERSITY_ID:
                raise ValueError("口コミの公開は宮崎大学の登録者が利用できます。")
            if record["reviewVersion"] == 2:
                nickname = profile.get("nickname", "")
                if not isinstance(nickname, str) or not nickname.strip():
                    raise ValueError("プロフィールでニックネームを登録してください。")
                record["nickname"] = nickname
            previous = connection.execute("SELECT payload FROM reviews WHERE user_id = ? AND visit_id = ?",
                                          (subject, record["id"])).fetchone()
            public = {"id": json.loads(previous[0])["id"] if previous else str(uuid4()),
                      "hospitalId": record["hospitalId"], "note": record["note"]}
            if record["reviewVersion"] == 2:
                public.update(nickname=record["nickname"], visitedMonth=visited_month(record["arrivalAt"]),
                              positivePoints=record["positivePoints"], sceneText=record["sceneText"],
                              adviceText=record["adviceText"], universityEmailVerified=university_email_verified is True)
            # Precise visit times require a separate opt-in, unlike the default month.
            if sharing["showGrade"]:
                public["gradeLabel"] = grade_label(profile["grade"])
            if sharing["showVisitTimes"]:
                public.update(arrivalAt=record["arrivalAt"], leaveAt=record["leaveAt"])
            for flag, field in (("showReservation", "reservationStatus"), ("showDuration", "stayMinutes"),
                                ("showFee", "feeAmount"), ("showVisitType", "visitType"), ("showWaiting", "waitingMinutes")):
                if record["reviewVersion"] == 1 and flag in {"showVisitType", "showWaiting"}:
                    continue
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
