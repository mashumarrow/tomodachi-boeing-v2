import json
import math
import os
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import jwt
from dotenv import load_dotenv
from database import connect_database as connect_records, lock_user


load_dotenv(Path(__file__).with_name(".env"), override=False)

DOMAIN = os.environ.get("AUTH0_DOMAIN", "").strip()
CLIENT_ID = os.environ.get("AUTH0_CLIENT_ID", "").strip()
AUDIENCE = os.environ.get("AUTH0_AUDIENCE", "").strip()
JWKS_CLIENT = jwt.PyJWKClient(f"https://{DOMAIN}/.well-known/jwks.json") if DOMAIN else None
UNIVERSITY_DATA = json.loads((Path(__file__).parent / "data" / "universities.json").read_text(encoding="utf-8"))
UNIVERSITIES = {item["id"]: item for item in UNIVERSITY_DATA["universities"]}
GRADES = {"1", "2", "3", "4", "5", "6", "master1", "master2", "doctor1", "doctor2", "doctor3", "other"}
GENDERS = {"female", "male", "other", "prefer_not_to_say"}
MIYAZAKI_UNIVERSITY_ID = "F145110111523"
REVIEW_UNIVERSITY_IDS = (MIYAZAKI_UNIVERSITY_ID,)
REVIEW_UNIVERSITY_PLACEHOLDERS = ",".join("%s" for _ in REVIEW_UNIVERSITY_IDS)
VERIFIED_EMAIL_DOMAINS = {
    "student.miyazaki-u.ac.jp": "miyazaki",
    **{f"mail{number}.doshisha.ac.jp": "doshisha" for number in ("", "1", "2", "3", "4")},
}
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


def email_verification_status(subject, authorization):
    request = Request(f"https://{DOMAIN}/userinfo", headers={"Authorization": authorization, "Accept": "application/json"})
    with urlopen(request, timeout=8) as response:
        data = json.loads(response.read(65536))
    result = {"universityEmailVerified": False, "verifiedEmailUniversity": None}
    if not isinstance(data, dict) or data.get("sub") != subject:
        return {**result, "status": "identity_mismatch"}
    email = data.get("email")
    if not isinstance(email, str) or email.count("@") != 1 or not email.partition("@")[0]:
        return {**result, "status": "missing_email"}
    university = VERIFIED_EMAIL_DOMAINS.get(email.partition("@")[2].lower())
    if not university:
        return {**result, "status": "unsupported_domain"}
    if data.get("email_verified") is not True:
        return {**result, "status": "email_unverified"}
    return {"universityEmailVerified": True, "verifiedEmailUniversity": university, "status": "verified"}


def verified_email_university(subject, authorization):
    return email_verification_status(subject, authorization)["verifiedEmailUniversity"]


def sync_review_email_badges(subject, university):
    if university not in ("miyazaki", "doshisha"):
        return 0
    updated = 0
    with connect_records() as connection:
        lock_user(connection, subject)
        rows = connection.execute("SELECT visit_id, payload FROM reviews WHERE user_id = %s", (subject,)).fetchall()
        for visit_id, payload in rows:
            review = json.loads(payload)
            if review.get("universityEmailVerified") is True and review.get("verifiedEmailUniversity") == university:
                continue
            review.update(universityEmailVerified=True, verifiedEmailUniversity=university)
            connection.execute("UPDATE reviews SET payload = %s WHERE user_id = %s AND visit_id = %s",
                               (json.dumps(review, ensure_ascii=False), subject, visit_id))
            updated += 1
    return updated


def visited_month(arrival_at):
    arrival = datetime.fromisoformat(arrival_at.replace("Z", "+00:00"))
    return arrival.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m")


def list_records(subject):
    with connect_records() as connection:
        rows = connection.execute("""
            SELECT v.payload, r.payload FROM visits v
            LEFT JOIN reviews r ON r.user_id = v.user_id AND r.visit_id = v.visit_id
            WHERE v.user_id = %s
        """, (subject,)).fetchall()
    records = []
    for payload, review_payload in rows:
        record = json.loads(payload)
        if review_payload:
            review = json.loads(review_payload)
            record["reviewProfile"] = {field: review[field] for field in
                                      ("nickname", "gradeLabel", "gradeBand", "universityEmailVerified", "verifiedEmailUniversity")
                                      if field in review}
        records.append(record)
    return records


def hospital_stay_averages(subject, hospital_ids):
    hospital_ids = list(dict.fromkeys(hospital_ids))
    if not hospital_ids:
        return {}
    placeholders = ",".join("%s" for _ in hospital_ids)
    # Shared durations follow the same publication and university rules as reviews.
    with connect_records() as connection:
        rows = connection.execute(f"""
            WITH durations AS (
                SELECT user_id, visit_id, payload::jsonb ->> 'hospitalId' AS hospital_id,
                       payload::jsonb ->> 'status' AS status,
                       CASE WHEN jsonb_typeof(payload::jsonb -> 'stayMinutes') = 'number'
                            THEN (payload::jsonb ->> 'stayMinutes')::numeric END AS stay_minutes
                FROM visits
            )
            SELECT v.hospital_id, AVG(v.stay_minutes), COUNT(*) FROM durations v
            WHERE v.hospital_id IN ({placeholders})
              AND v.status = 'completed' AND v.stay_minutes > 0
              AND (
                  v.user_id = %s OR (
                      EXISTS (
                          SELECT 1 FROM profiles viewer
                          WHERE viewer.user_id = %s
                            AND viewer.payload::jsonb ->> 'universityId' IN ({REVIEW_UNIVERSITY_PLACEHOLDERS})
                      )
                      AND EXISTS (
                          SELECT 1 FROM reviews r JOIN profiles author ON author.user_id = r.user_id
                          WHERE r.user_id = v.user_id AND r.visit_id = v.visit_id
                            AND r.hospital_id = v.hospital_id
                            AND jsonb_typeof(r.payload::jsonb -> 'stayMinutes') = 'number'
                            AND author.payload::jsonb ->> 'universityId' IN ({REVIEW_UNIVERSITY_PLACEHOLDERS})
                      )
                  )
              )
            GROUP BY hospital_id
        """, (*hospital_ids, subject, subject, *REVIEW_UNIVERSITY_IDS, *REVIEW_UNIVERSITY_IDS)).fetchall()
    return {hospital_id: {"averageStayMinutes": math.ceil(average), "staySampleCount": count}
            for hospital_id, average, count in rows}


def hospital_fee_averages(subject, hospital_ids):
    hospital_ids = list(dict.fromkeys(hospital_ids))
    if not hospital_ids:
        return {}
    placeholders = ",".join("%s" for _ in hospital_ids)
    with connect_records() as connection:
        rows = connection.execute(f"""
            SELECT r.hospital_id, r.payload::jsonb ->> 'feeAmount'
            FROM reviews r
            JOIN profiles author ON author.user_id = r.user_id
            JOIN profiles viewer ON viewer.user_id = %s
            WHERE r.hospital_id IN ({placeholders})
              AND author.payload::jsonb ->> 'universityId' IN ({REVIEW_UNIVERSITY_PLACEHOLDERS})
              AND viewer.payload::jsonb ->> 'universityId' IN ({REVIEW_UNIVERSITY_PLACEHOLDERS})
              AND jsonb_typeof(r.payload::jsonb -> 'feeAmount') IN ('number', 'string')
        """, (subject, *hospital_ids, *REVIEW_UNIVERSITY_IDS, *REVIEW_UNIVERSITY_IDS)).fetchall()
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
        row = connection.execute("SELECT payload FROM profiles WHERE user_id = %s", (subject,)).fetchone()
    return json.loads(row[0]) if row else None


def save_profile(subject, value, *, require_existing=False):
    if not isinstance(value, dict):
        raise ValueError("プロフィールの形式が正しくありません。")
    university_id = MIYAZAKI_UNIVERSITY_ID
    grade = value.get("grade")
    gender = value.get("gender")
    nickname = value.get("nickname")
    if not isinstance(nickname, str) or not nickname.strip() or len(nickname) > 20:
        raise ValueError("ニックネームは1〜20文字で入力してください。")
    if not isinstance(grade, str) or grade not in GRADES:
        raise ValueError("学年を選択してください。")
    if not isinstance(gender, str) or gender not in GENDERS:
        raise ValueError("性別または回答しないを選択してください。")
    profile = {"universityId": university_id, "universityName": UNIVERSITIES[university_id]["name"],
               "grade": grade, "gender": gender, "nickname": nickname.strip()}
    with connect_records() as connection:
        lock_user(connection, subject)
        if require_existing and not connection.execute("SELECT 1 FROM profiles WHERE user_id = %s", (subject,)).fetchone():
            raise ValueError("プロフィールがありません。もう一度ログインしてください。")
        connection.execute("INSERT INTO profiles (user_id, payload) VALUES (%s, %s) "
                           "ON CONFLICT(user_id) DO UPDATE SET payload = excluded.payload",
                           (subject, json.dumps(profile, ensure_ascii=False)))
    return profile


def delete_account(subject):
    with connect_records() as connection:
        lock_user(connection, subject)
        for table in ("reviews", "visits", "profiles"):
            connection.execute(f"DELETE FROM {table} WHERE user_id = %s", (subject,))


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
        selected = sharing.get(field, field != "published")
        if not isinstance(selected, bool):
            raise ValueError("口コミの公開設定が正しくありません。")
        result["reviewSharing"][field] = True if field == "showVisitTimes" else selected
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


def public_review_payload(record, profile, previous=None, verified_email_university=None):
    sharing = record.get("reviewSharing", {})
    public = {"id": previous["id"] if previous else str(uuid4()),
              "hospitalId": record["hospitalId"], "note": record.get("note", "")}
    if record.get("reviewVersion", 1) == 2:
        verified = verified_email_university in ("miyazaki", "doshisha")
        public.update(nickname=profile.get("nickname", ""), visitedMonth=visited_month(record["arrivalAt"]),
                      positivePoints=record.get("positivePoints", []), sceneText=record.get("sceneText", ""),
                      adviceText=record.get("adviceText", ""), universityEmailVerified=verified)
        if verified:
            public["verifiedEmailUniversity"] = verified_email_university
    if sharing.get("showGrade", True):
        public["gradeLabel"] = grade_label(profile.get("grade", ""))
    public.update(arrivalAt=record["arrivalAt"], leaveAt=record["leaveAt"])
    for flag, field in (("showReservation", "reservationStatus"), ("showDuration", "stayMinutes"),
                        ("showFee", "feeAmount"), ("showVisitType", "visitType"), ("showWaiting", "waitingMinutes")):
        if record.get("reviewVersion", 1) == 1 and flag in {"showVisitType", "showWaiting"}:
            continue
        if sharing.get(flag, True) and field in record:
            public[field] = record[field]
    return public


def publish_all_reviews(subject=None):
    updated = 0
    with connect_records() as connection:
        if subject is None:
            connection.execute("LOCK TABLE profiles, visits, reviews IN SHARE ROW EXCLUSIVE MODE")
        else:
            lock_user(connection, subject)
        rows = connection.execute(f"""
            SELECT v.user_id, v.visit_id, v.payload, p.payload, r.payload
            FROM visits v JOIN profiles p ON p.user_id = v.user_id
            LEFT JOIN reviews r ON r.user_id = v.user_id AND r.visit_id = v.visit_id
            WHERE p.payload::jsonb ->> 'universityId' IN ({REVIEW_UNIVERSITY_PLACEHOLDERS})
              AND v.payload::jsonb ->> 'status' = 'completed'
              AND (r.visit_id IS NULL OR COALESCE(v.payload::jsonb #>> '{{reviewSharing,published}}', 'false') <> 'true')
              AND (%s::text IS NULL OR v.user_id = %s)
        """, (*REVIEW_UNIVERSITY_IDS, subject, subject)).fetchall()
        for owner, visit_id, payload, profile_payload, previous_payload in rows:
            record, profile = json.loads(payload), json.loads(profile_payload)
            # Historical records can predate today's required fee and review fields.
            try:
                arrival = datetime.fromisoformat(record["arrivalAt"].replace("Z", "+00:00"))
                leave = datetime.fromisoformat(record["leaveAt"].replace("Z", "+00:00"))
                if not arrival.tzinfo or not leave.tzinfo or leave < arrival or not record.get("hospitalId"):
                    continue
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            record["reviewSharing"] = {**record.get("reviewSharing", {}), "published": True, "showVisitTimes": True}
            record["stayMinutes"] = max(1, round((leave - arrival).total_seconds() / 60))
            if not previous_payload:
                public = public_review_payload(record, profile)
                public.update(nickname=profile.get("nickname", ""), visitedMonth=visited_month(record["arrivalAt"]))
                connection.execute("INSERT INTO reviews (user_id, visit_id, hospital_id, payload) VALUES (%s, %s, %s, %s)",
                                   (owner, visit_id, record["hospitalId"], json.dumps(public, ensure_ascii=False)))
            connection.execute("UPDATE visits SET payload = %s WHERE user_id = %s AND visit_id = %s",
                               (json.dumps(record, ensure_ascii=False), owner, visit_id))
            updated += 1
    return updated


def save_record(subject, value, *, verified_email_university=None):
    record = validate_record(value)
    with connect_records() as connection:
        lock_user(connection, subject)
        sharing = record["reviewSharing"]
        if sharing["published"]:
            profile_row = connection.execute("SELECT payload FROM profiles WHERE user_id = %s", (subject,)).fetchone()
            profile = json.loads(profile_row[0]) if profile_row else {}
            if profile.get("universityId") not in REVIEW_UNIVERSITY_IDS:
                raise ValueError("口コミの公開は宮崎大学の登録者が利用できます。")
            if record["reviewVersion"] == 2:
                nickname = profile.get("nickname", "")
                if not isinstance(nickname, str) or not nickname.strip():
                    raise ValueError("プロフィールでニックネームを登録してください。")
                record["nickname"] = nickname
            previous = connection.execute("SELECT payload FROM reviews WHERE user_id = %s AND visit_id = %s",
                                          (subject, record["id"])).fetchone()
            public = public_review_payload(record, profile, json.loads(previous[0]) if previous else None,
                                           verified_email_university)
            connection.execute("""
                INSERT INTO reviews (user_id, visit_id, hospital_id, payload) VALUES (%s, %s, %s, %s)
                ON CONFLICT(user_id, visit_id) DO UPDATE SET hospital_id = excluded.hospital_id, payload = excluded.payload
            """, (subject, record["id"], record["hospitalId"], json.dumps(public, ensure_ascii=False)))
        else:
            connection.execute("DELETE FROM reviews WHERE user_id = %s AND visit_id = %s", (subject, record["id"]))
        connection.execute("""
            INSERT INTO visits (user_id, visit_id, payload) VALUES (%s, %s, %s)
            ON CONFLICT(user_id, visit_id) DO UPDATE SET payload = excluded.payload
        """, (subject, record["id"], json.dumps(record, ensure_ascii=False)))
    return record


def list_reviews(subject, hospital_id):
    with connect_records() as connection:
        rows = connection.execute(f"""
            SELECT r.user_id, r.payload, v.payload FROM reviews r JOIN profiles p ON p.user_id = r.user_id
            LEFT JOIN visits v ON v.user_id = r.user_id AND v.visit_id = r.visit_id
            WHERE r.hospital_id = %s AND p.payload::jsonb ->> 'universityId' IN ({REVIEW_UNIVERSITY_PLACEHOLDERS})
            ORDER BY r.review_order DESC LIMIT 50
        """, (hospital_id, *REVIEW_UNIVERSITY_IDS)).fetchall()
    reviews = []
    for owner, payload, visit_payload in rows:
        public = {**json.loads(payload), "isOwnRecord": owner == subject}
        # Older public snapshots may omit times; use only their matching visit.
        if visit_payload:
            visit = json.loads(visit_payload)
            if visit.get("arrivalAt") and visit.get("leaveAt"):
                public.update(arrivalAt=visit["arrivalAt"], leaveAt=visit["leaveAt"])
        reviews.append(public)
    return reviews


def unpublish_review(subject, visit_id):
    with connect_records() as connection:
        lock_user(connection, subject)
        row = connection.execute("SELECT payload FROM visits WHERE user_id = %s AND visit_id = %s",
                                 (subject, visit_id)).fetchone()
        if not row:
            raise ValueError("受診記録が見つかりません。")
        record = json.loads(row[0])
        record["reviewSharing"] = {**record.get("reviewSharing", {}), "published": False}
        connection.execute("DELETE FROM reviews WHERE user_id = %s AND visit_id = %s", (subject, visit_id))
        connection.execute("UPDATE visits SET payload = %s WHERE user_id = %s AND visit_id = %s",
                           (json.dumps(record, ensure_ascii=False), subject, visit_id))
    return record
