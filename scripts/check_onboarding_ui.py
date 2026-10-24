import base64
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
import server
import user_records
from tests.db_support import isolated_database


SDK = """
window.auth0 = { Auth0Client: function () { return {
  checkSession: async () => {
    window.sessionChecks = (window.sessionChecks || 0) + 1;
    if (window.testSessionError) throw {error: 'login_required'};
  },
  handleRedirectCallback: async () => {
    window.callbackChecks = (window.callbackChecks || 0) + 1;
    await new Promise(resolve => setTimeout(resolve, 300));
    if (window.testCallbackError) throw new Error('Invalid state');
    window.testLoggedIn = true;
  },
  isAuthenticated: async () => window.testLoggedIn,
  getUser: async () => ({sub: 'test-user', name: 'Test User', picture: window.testPicture}),
  getTokenSilently: async (options) => {
    if (options.cacheMode === 'off') window.tokenRefreshes = (window.tokenRefreshes || 0) + 1;
    return 'test-token';
  },
  loginWithRedirect: async (options) => { window.loginOptions = options || {}; },
  logout: async (options) => {
    window.logoutChecks = (window.logoutChecks || 0) + 1;
    window.logoutOptions = options;
    await new Promise(resolve => setTimeout(resolve, window.testLogoutDelay || 0));
    if (window.testLogoutError) throw new Error('Logout unavailable');
    window.testLoggedIn = false;
  },
}; } };
"""


def search_at_nine(page):
    assert page.locator('[data-when], #when, .scheduled-time').count() == 0
    assert page.locator("#startTime").is_visible()
    assert page.locator("#startTime").evaluate("input => getComputedStyle(input.parentElement).backgroundColor") == "rgba(0, 0, 0, 0)"
    page.fill("#startTime", "09:00")
    page.fill("#returnTime", "10:30")
    page.click('#searchForm button[type="submit"]')


def assert_hospital_estimate(page, hospital_id, stay_minutes):
    card = page.locator(f'.hospital-card:has([data-plan="{hospital_id}"])')
    card.wait_for()
    times = [int(text.removesuffix("分")) for text in card.locator(".time-breakdown div strong").all_text_contents()]
    assert times[1] == stay_minutes, times
    total = sum(times)
    return_at = 9 * 60 + total
    assert card.locator(".result-highlight > strong").inner_text() == f"{return_at // 60:02}:{return_at % 60:02}ごろ"
    assert f"約{total}分" in card.locator(".duration-summary").inner_text()
    remaining = 90 - total
    expected_fit = "余裕あり" if remaining >= 30 else "間に合いそう" if remaining >= 10 else "余裕少なめ" if remaining >= 0 else "厳しそう"
    assert card.locator(".badge").inner_text() == expected_fit
    return card


def check_auth_redirect(browser, url):
    for scenario in ("success", "nickname_missing", "callback_error", "api_rejected", "login_required"):
        context = browser.new_context(viewport={"width": 375, "height": 820})
        context.route("https://unpkg.com/**", lambda route: route.abort())
        context.route("https://cdn.auth0.com/**", lambda route: route.fulfill(
            body=SDK, content_type="application/javascript"))
        context.route("**/api/visits", lambda route: route.fulfill(
            body='{"visits":[]}', content_type="application/json"))
        profile = {"universityName": "宮崎大学", "universityId": "F145110111523",
                   "grade": "4", "gender": "prefer_not_to_say"}
        if scenario != "nickname_missing":
            profile["nickname"] = "ひなた"
        if scenario == "api_rejected":
            context.route("**/api/profile", lambda route: route.fulfill(
                status=401, body='{"error":"Audience mismatch","code":"invalid_audience"}',
                content_type="application/json"))
        else:
            context.route("**/api/profile", lambda route: route.fulfill(
                body=json.dumps({"profile": profile}), content_type="application/json"))
        page = context.new_page()
        page.add_init_script(f"window.testCallbackError = {str(scenario == 'callback_error').lower()};")
        page.add_init_script(f"window.testSessionError = {str(scenario == 'login_required').lower()};")
        callback_url = url if scenario == "login_required" else f"{url}?code=test-code&state=test-state&keep=1"
        page.goto(callback_url)
        if scenario != "login_required":
            page.wait_for_function("window.callbackChecks === 1")
            assert page.locator("#loginScreen").is_hidden()
        page.locator("#loginButton:enabled").wait_for(state="attached")
        if scenario == "success":
            assert page.locator("#appContent").is_visible()
            assert page.locator("#loginScreen").is_hidden()
            mascot = page.locator("#searchForm + .search-mascot img")
            assert mascot.is_visible()
            assert mascot.evaluate("image => image.complete && image.naturalWidth > 0")
            assert mascot.evaluate(
                "image => image.getBoundingClientRect().top >= "
                "image.closest('.search-mascot').previousElementSibling.getBoundingClientRect().bottom"
            )
            assert page.locator(".search-mascot").count() == 3
            assert page.locator("#searchForm + .search-mascot").is_visible()
            assert page.locator("#screen-results .search-mascot").count() == 1
            assert page.locator("#screen-active .search-mascot").count() == 1
            assert page.evaluate("window.sessionChecks || 0") == 0
            page.add_init_script("window.testLoggedIn = true;")
            page.reload()
            page.locator("#appContent").wait_for(state="visible")
            assert page.evaluate("window.sessionChecks") == 1
            assert page.evaluate("window.callbackChecks || 0") == 0
        elif scenario == "nickname_missing":
            page.locator("#profileScreen").wait_for(state="visible")
            assert page.locator("#universitySelect, #universitySearch").count() == 0
            assert page.locator("#appContent").is_hidden()
            assert page.locator("#profileNickname").input_value() == ""
            assert page.locator("#profileGrade").input_value() == "4"
            assert page.locator("#profileGender").input_value() == "prefer_not_to_say"
        else:
            assert page.locator("#loginScreen").is_visible()
            assert page.locator("#appContent").is_hidden()
            if scenario == "callback_error":
                assert page.locator("#accountStatus").inner_text() == "Invalid state"
            elif scenario == "api_rejected":
                assert "invalid_audience" in page.locator("#accountStatus").inner_text()
                assert page.evaluate("window.tokenRefreshes") == 1
            else:
                assert page.locator("#accountStatus").inner_text() == ""
        assert "code=" not in page.url and "state=" not in page.url
        context.close()
    print("Auth callback, reload, denied token and callback error checks passed")


def check_account_logout(browser, url):
    avatar_png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQ0AAAAASUVORK5CYII=")
    for scenario in ("success", "sdk_error", "profile"):
        context = browser.new_context(viewport={"width": 375, "height": 820})
        context.route("https://unpkg.com/**", lambda route: route.abort())
        context.route("https://cdn.auth0.com/**", lambda route: route.fulfill(
            body=SDK, content_type="application/javascript"))
        context.route("https://avatars.example.test/**", lambda route: route.fulfill(
            status=404 if scenario == "sdk_error" else 200,
            body=b"" if scenario == "sdk_error" else avatar_png, content_type="image/png"))
        profile = {"universityName": "宮崎大学", "universityId": "F145110111523",
                   "nickname": "あ" * 20 if scenario == "sdk_error" else "ひなた", "grade": "4", "gender": "female"}
        context.route("**/api/profile", lambda route: route.fulfill(
            body=json.dumps({"profile": None if scenario == "profile" else profile}), content_type="application/json"))
        context.route("**/api/visits", lambda route: route.fulfill(
            body='{"visits":[]}', content_type="application/json"))
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("window.testLoggedIn = true; window.testLogoutDelay = 100; window.testPicture = 'https://avatars.example.test/user.png';")
        page.add_init_script(f"window.testLogoutError = {str(scenario == 'sdk_error').lower()};")
        page.goto(url)
        pending_requests = []
        if scenario == "profile":
            page.locator("#profileScreen").wait_for(state="visible")
            page.click("#profileLogoutButton")
        else:
            page.locator("#appContent").wait_for(state="visible")
            if scenario == "success":
                page.wait_for_function("document.querySelector('#accountAvatar').naturalWidth === 1")
                assert page.locator("#accountAvatar").is_visible()
                assert page.locator("#accountInitial").is_hidden()
                context.route("**/api/profile?late=1", lambda route: pending_requests.append(route))
                with page.expect_request("**/api/profile?late=1"):
                    page.evaluate("void authorizedFetch('/api/profile?late=1').then(() => { window.lateResult = 'accepted'; }).catch(error => { window.lateResult = error.message; });")
            else:
                page.wait_for_function("document.querySelector('#accountAvatar').complete")
                assert page.locator("#accountAvatar").is_hidden()
                assert page.locator("#accountInitial").inner_text() == "あ"
            page.click("#accountButton")
            assert page.locator("#accountNickname").inner_text() == profile["nickname"]
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            page.click("#logoutButton")
        page.locator("#loginScreen").wait_for(state="visible")
        page.locator("#loginButton:enabled").wait_for()
        assert page.locator("#appContent").is_hidden()
        assert page.locator("#profileScreen").is_hidden()
        assert page.evaluate("window.logoutChecks") == 1
        assert page.evaluate("window.logoutOptions") == {"logoutParams": {"returnTo": url}}
        assert page.evaluate("sessionStorage.getItem('campusClinicSignedOut')") == "1"
        assert page.locator("#accountNickname").text_content() == ""
        assert page.locator("#accountAvatar").get_attribute("src") is None
        if scenario == "sdk_error":
            assert "アプリからログアウトしました" in page.locator("#accountStatus").inner_text()
        if pending_requests:
            pending_requests[0].fulfill(body=json.dumps({"profile": profile}), content_type="application/json")
            page.wait_for_function("Boolean(window.lateResult)")
            assert page.evaluate("window.lateResult") == "ログイン状態が変更されました。"
        page.reload()
        page.locator("#loginButton:enabled").wait_for()
        assert page.locator("#appContent").is_hidden()
        assert page.evaluate("window.sessionChecks || 0") == 0
        page.click("#loginButton")
        assert page.evaluate("window.loginOptions.authorizationParams.prompt") == "login"
        page.goto(f"{url}?code=test-code&state=test-state")
        page.locator("#profileScreen" if scenario == "profile" else "#appContent").wait_for(state="visible")
        assert page.evaluate("sessionStorage.getItem('campusClinicSignedOut')") is None
        assert errors == [], errors
        context.close()
    print("Avatar, failed picture, logout failure, reload, late response and re-login checks passed")


def check_review_layout(browser, url):
    fixtures = [
        {"nickname": "あ" * 20, "visitedMonth": "2026-10", "gradeLabel": "学部3年", "visitType": "初診",
         "reservationStatus": "予約なし", "universityEmailVerified": True, "waitingMinutes": 0, "stayMinutes": 60,
         "feeAmount": "10000000", "positivePoints": list(user_records.POSITIVE_POINTS[:-1]),
         "sceneText": "薬の説明をしてくれました。\n" + "longtext" * 35,
         "adviceText": '<img src=x onerror="window.reviewInjected=true">', "isOwnRecord": True},
        {"nickname": "こもれび", "gradeBand": "学部1〜2年", "note": "以前の形式の口コミも読めます。", "feeAmount": "0", "privateRecord": True},
        {"visitedMonth": "2026-99", "feeAmount": "", "waitingMinutes": None, "stayMinutes": None},
        {"nickname": "ひなた", "visitType": "初診", "reservationStatus": "予約あり", "positivePoints": ["説明が分かりやすい"]},
        {"nickname": "ひなた", "gradeLabel": "学部4年", "visitedMonth": "2026-10", "visitType": "初診", "reservationStatus": "予約あり",
         "positivePoints": ["質問しやすい"], "arrivalAt": "2026-10-21T02:00:00Z", "leaveAt": "2026-10-21T03:00:00Z",
         "sceneText": "先生が優しい", "adviceText": "時間に余裕をもつとよさそう"},
    ]
    for width in (320, 375, 1280):
        context = browser.new_context(viewport={"width": width, "height": 820})
        context.route("https://unpkg.com/**", lambda route: route.abort())
        context.route("https://cdn.auth0.com/**", lambda route: route.fulfill(
            body=SDK, content_type="application/javascript"))
        context.route("**/api/profile", lambda route: route.fulfill(
            body=json.dumps({"profile": {"nickname": "ひなた", "universityName": "宮崎大学", "universityId": user_records.MIYAZAKI_UNIVERSITY_ID}}), content_type="application/json"))
        context.route("**/api/visits", lambda route: route.fulfill(
            body='{"visits":[]}', content_type="application/json"))
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("window.testLoggedIn = true;")
        page.goto(url)
        page.locator("#appContent").wait_for(state="visible")
        page.evaluate("""posts => {
            state.reviewFeeds.set('layout-fixture', {posts});
            document.querySelector('#detail').innerHTML = `<section class="detail-reviews"><div class="community-feed">${renderReviewCards({id: 'layout-fixture'})}</div></section>`;
            navigate('detail');
        }""", fixtures)
        cards = page.locator(".community-card")
        assert cards.count() == 5
        assert cards.nth(0).locator(".review-author strong").inner_text() == "あ" * 20
        assert cards.nth(0).locator(".review-month time").get_attribute("datetime") == "2026-10"
        assert cards.nth(0).locator(".review-month").inner_text() == "2026年10月"
        assert cards.nth(0).locator(".review-author > span").inner_text() == "学部3年"
        assert cards.nth(1).locator(".review-author > span").inner_text() == "学部1〜2年"
        assert cards.nth(0).locator(".review-metrics").inner_text().startswith("待ち時間")
        assert "0分" in cards.nth(0).locator(".review-metrics").inner_text().replace("\n", "")
        assert cards.nth(0).locator(".review-note img").count() == 0
        assert cards.nth(0).locator(".review-narrative h5").first.inner_text() == "よかった点の具体的なエピソード"
        assert cards.nth(0).locator(".review-narrative").first.evaluate("""section => {
            const heading = getComputedStyle(section.querySelector('h5'));
            const body = getComputedStyle(section.querySelector('.review-note'));
            return Number(heading.fontWeight) >= 700 && Number(body.fontWeight) < 700
                && body.backgroundColor !== 'rgba(0, 0, 0, 0)' && parseFloat(body.borderLeftWidth) > 0;
        }""")
        assert not page.evaluate("Boolean(window.reviewInjected)")
        assert cards.nth(1).locator(".review-metrics").inner_text().replace("\n", "") == "費用0円"
        assert cards.nth(2).locator(".review-metrics, .review-month, .review-body, .review-tags").count() == 0
        tags = cards.nth(3).locator(".review-tags li")
        assert tags.all_text_contents() == ["初診", "予約あり", "説明が分かりやすい"]
        tag_rows = tags.evaluate_all("elements => elements.map(element => element.getBoundingClientRect().top)")
        assert max(tag_rows) - min(tag_rows) <= 1
        assert cards.nth(3).locator(".review-body").count() == 0
        assert cards.nth(4).locator(".review-month").count() == 0
        assert cards.nth(4).locator(".review-visit-times time").all_text_contents() == ["2026年10月21日 11:00", "12:00"]
        badge = cards.nth(0).locator(".community-card-header .review-verified")
        assert badge.get_attribute("aria-label") == "宮崎大学メール認証済み"
        assert badge.inner_text() == "認証済み"
        badge.locator("img").evaluate("image => image.decode()")
        assert badge.locator("img").evaluate("image => image.naturalWidth > 0 && image.naturalHeight > 0")
        assert "大学による公式認定ではありません" in badge.get_attribute("title")
        assert cards.nth(1).locator(".review-verified").count() == 0
        assert cards.nth(0).locator(".community-card-header").evaluate("""header => {
            const author = header.querySelector('.review-author').getBoundingClientRect();
            const badge = header.querySelector('.review-verified').getBoundingClientRect();
            const bounds = header.getBoundingClientRect();
            return author.right <= badge.left && Math.abs(badge.right - bounds.right) <= 1
                && Math.abs((author.top + author.bottom) / 2 - (bounds.top + bounds.bottom) / 2) <= 1;
        }""")
        for verified, university, expected in (
            (True, "miyazaki", "宮崎大学メール認証済み"),
            (True, "doshisha", "同志社大学メール認証済み"),
            (False, "doshisha", ""), (True, "unknown", ""), (True, "constructor", ""),
        ):
            badge = page.evaluate("""post => {
                const element = document.createElement('div');
                element.innerHTML = reviewContentMarkup(post);
                return element.querySelector('.review-verified')?.getAttribute('aria-label') || '';
            }""", {"universityEmailVerified": verified, "verifiedEmailUniversity": university})
            assert badge == expected
        assert "2026年10月22日 00:30" in page.evaluate("reviewVisitTimesMarkup({arrivalAt: '2026-10-21T14:30:00Z', leaveAt: '2026-10-21T15:30:00Z'})")
        assert page.evaluate("reviewVisitTimesMarkup({arrivalAt: 'invalid', leaveAt: 'invalid'})") == ""
        assert page.evaluate("reviewVisitTimesMarkup({arrivalAt: '2026-10-22T00:00:00Z', leaveAt: '2026-10-21T00:00:00Z'})") == ""
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        assert page.locator(".community-card, .review-author, .review-metrics dd").evaluate_all(
            "elements => elements.every(element => element.scrollWidth <= element.clientWidth + 1)")
        cards.nth(0).screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-review-long-{width}.png"))
        cards.nth(3).screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-review-tags-{width}.png"))
        cards.nth(4).screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-review-sections-{width}.png"))
        assert errors == [], errors
        context.close()
    print("Review layout checks passed for long names, long text, missing fields, zero values and legacy notes")


def check_account_settings(browser, url):
    for width in (320, 375, 1280):
        for subject in ("test-user", "settings-other"):
            user_records.save_profile(subject, {"nickname": "ひなた", "grade": "4", "gender": "female"})
            user_records.save_record(subject, {"id": "settings-visit", "hospitalId": "clinic:1", "hospitalName": "テスト病院",
                "department": "internal", "plannedAt": "2026-10-21T00:00:00Z", "arrivalAt": "2026-10-21T01:00:00Z",
                "leaveAt": "2026-10-21T01:30:00Z", "feeAmount": "1200", "reservationStatus": "予約なし",
                "waitingImpression": "未入力", "reviewVersion": 2, "visitType": "初診", "positivePoints": ["その他"],
                "sceneText": "保存済みの文章", "reviewSharing": {"published": True}})
        context = browser.new_context(viewport={"width": width, "height": 820}, timezone_id="Asia/Tokyo")
        context.route("https://unpkg.com/**", lambda route: route.abort())
        context.route("https://cdn.auth0.com/**", lambda route: route.fulfill(body=SDK, content_type="application/javascript"))
        pending_save, pending_delete = [], []
        def settings_route(route):
            if route.request.method == "PUT" and not pending_save:
                pending_save.append(route)
            else:
                route.continue_()
        def delete_route(route):
            if not pending_delete:
                pending_delete.append(route)
            else:
                route.continue_()
        context.route("**/api/profile", settings_route)
        context.route("**/api/account", delete_route)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("window.testLoggedIn = true;")
        page.goto(url)
        page.locator("#appContent").wait_for(state="visible")
        page.click('.tab[data-nav="log"]')
        page.click("#accountButton")
        page.click("#settingsButton")
        assert page.locator("#screen-settings").is_visible()
        assert page.locator(".tabbar").is_hidden()
        assert page.locator("#settingsNickname").input_value() == "ひなた"
        assert page.locator("#settingsGrade").input_value() == "4"
        assert page.locator("#settingsGender").input_value() == "female"
        page.fill("#settingsNickname", " ")
        page.click("#settingsSaveButton")
        assert not pending_save
        page.fill("#settingsNickname", "こもれび")
        page.select_option("#settingsGrade", "master2")
        page.select_option("#settingsGender", "prefer_not_to_say")
        page.click("#settingsSaveButton")
        assert page.locator("#settingsSaveButton").is_disabled()
        assert page.locator("#withdrawButton").is_disabled()
        assert page.locator("#settingsNickname").is_disabled()
        pending_save[0].fulfill(status=503, body='{"error":"保存に失敗しました"}', content_type="application/json")
        page.wait_for_function("!state.savingSettings")
        assert "保存に失敗" in page.locator("#settingsStatus").inner_text()
        assert user_records.get_profile("test-user")["nickname"] == "ひなた"
        page.click("#settingsSaveButton")
        page.wait_for_function("document.querySelector('#settingsStatus').textContent.includes('変更を保存しました')")
        assert user_records.get_profile("test-user")["nickname"] == "こもれび"
        assert user_records.get_profile("test-user")["grade"] == "master2"
        assert user_records.list_reviews("test-user", "clinic:1")[0]["nickname"] == "ひなた"
        assert page.locator("#accountNickname").inner_text() == "こもれび"
        assert page.locator("#accountInitial").inner_text() == "こ"
        page.click("#settingsBackButton")
        assert page.locator("#screen-log").is_visible()
        assert page.locator(".tabbar").is_visible()
        page.reload()
        page.locator("#appContent").wait_for(state="visible")
        page.click("#accountButton")
        page.click("#settingsButton")
        assert page.locator("#settingsNickname").input_value() == "こもれび"
        assert page.locator("#settingsGrade").input_value() == "master2"
        assert page.locator("#settingsGender").input_value() == "prefer_not_to_say"
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-account-settings-{width}.png"), full_page=True)
        page.click("#withdrawButton")
        assert page.locator("#confirmDeleteAccount").is_disabled()
        page.click("#cancelDeleteAccount")
        assert not page.locator("#deleteAccountDialog").is_visible()
        assert user_records.get_profile("test-user") is not None
        page.click("#withdrawButton")
        page.keyboard.press("Escape")
        assert not page.locator("#deleteAccountDialog").is_visible()
        page.click("#withdrawButton")
        page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-withdraw-confirmation-{width}.png"))
        page.check("#deleteAccountConfirmed")
        page.click("#confirmDeleteAccount")
        assert page.locator("#confirmDeleteAccount").is_disabled()
        assert page.locator("#cancelDeleteAccount").is_disabled()
        page.keyboard.press("Escape")
        assert page.locator("#deleteAccountDialog").is_visible()
        pending_delete[0].fulfill(status=503, body='{"error":"削除に失敗しました"}', content_type="application/json")
        page.wait_for_function("!state.deletingAccount")
        assert "削除に失敗" in page.locator("#deleteAccountStatus").inner_text()
        assert user_records.get_profile("test-user") is not None
        page.evaluate("""() => {
            localStorage.setItem('campusClinicActiveVisit:test-user', '{"id":"draft"}');
            localStorage.setItem('campusClinicActiveVisit:someone-else', 'keep');
        }""")
        page.click("#confirmDeleteAccount")
        page.locator("#loginScreen").wait_for(state="visible")
        page.wait_for_function("!state.loggingOut")
        assert user_records.get_profile("test-user") is None
        assert user_records.list_records("test-user") == []
        assert len(user_records.list_records("settings-other")) == 1
        assert len(user_records.list_reviews("settings-other", "clinic:1")) == 1
        assert page.evaluate("localStorage.getItem('campusClinicActiveVisit:test-user')") is None
        assert page.evaluate("localStorage.getItem('campusClinicActiveVisit:someone-else')") == "keep"
        assert page.locator("#settingsNickname").input_value() == ""
        assert page.locator("#monthDetails").inner_text() == ""
        assert page.evaluate("sessionStorage.getItem('campusClinicSignedOut')") == "1"
        page.goto(f"{url}?code=test-code&state=test-state")
        page.locator("#profileScreen").wait_for(state="visible")
        assert page.locator("#appContent").is_hidden()
        assert errors == [], errors
        context.close()
        with user_records.connect_records() as connection:
            for table in ("reviews", "visits", "profiles"):
                connection.execute(f"DELETE FROM {table}")
    print("Account settings passed: validation, pending save, retry, persistence, confirmation, deletion, logout and fresh registration")


def check_personal_log_layout(browser, url):
    fixtures = [
        {"id": "log-layout-1", "hospitalId": "clinic:1", "hospitalName": "とても長い名前の病院" * 3,
         "department": "internal", "arrivalAt": "2026-10-21T14:30:00Z", "leaveAt": "2026-10-21T15:30:00Z",
         "stayMinutes": 60, "feeAmount": "1840", "visitType": "初診", "reservationStatus": "予約あり",
         "positivePoints": ["説明が分かりやすい", "質問しやすい"], "sceneText": "薬の説明を紙に書いてくれた。",
         "adviceText": "longtext" * 30, "reviewSharing": {"published": True},
         "reviewProfile": {"nickname": "あ" * 20, "gradeLabel": "学部2年", "universityEmailVerified": True,
                           "verifiedEmailUniversity": "doshisha"}},
        {"id": "log-layout-2", "hospitalId": "clinic:2", "hospitalName": '<img src=x onerror="window.logInjected=true">',
         "department": "internal", "arrivalAt": "2026-10-21T01:00:00Z", "leaveAt": "2026-10-21T01:30:00Z",
         "stayMinutes": 30, "feeAmount": "0", "reservationStatus": "予約なし", "note": "以前の形式の記録",
         "reviewSharing": {"published": True}},
    ]
    for width in (320, 375, 1280):
        context = browser.new_context(viewport={"width": width, "height": 820}, timezone_id="Asia/Tokyo")
        context.route("https://unpkg.com/**", lambda route: route.abort())
        context.route("https://cdn.auth0.com/**", lambda route: route.fulfill(body=SDK, content_type="application/javascript"))
        context.route("**/api/profile", lambda route: route.fulfill(body=json.dumps({"profile": {
            "nickname": "ひなた", "grade": "4", "universityId": user_records.MIYAZAKI_UNIVERSITY_ID,
            "universityName": "宮崎大学"}}), content_type="application/json"))
        context.route("**/api/visits", lambda route: route.fulfill(body='{"visits":[]}', content_type="application/json"))
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("window.testLoggedIn = true;")
        page.goto(url)
        page.locator("#appContent").wait_for(state="visible")
        page.wait_for_function("state.emailVerification && state.emailVerification.status !== 'checking'")
        page.evaluate("""visits => {
            state.visits = visits; state.calendarDate = new Date(2026, 9, 21); state.selectedDate = '2026-10-21';
            state.recordView = 'month'; renderCalendar(); navigate('log');
        }""", fixtures)
        cards = page.locator("#monthDetails .personal-record.community-card")
        assert cards.count() == 2
        first = cards.first
        assert first.locator(".record-hospital h4").inner_text() == fixtures[0]["hospitalName"]
        assert cards.locator(".community-card-header, .review-avatar, .review-author, .review-verified, .review-visibility").count() == 0
        assert "公開中" not in page.locator("#monthDetails").inner_text()
        assert first.locator(".review-tags li").all_text_contents() == ["初診", "予約あり", "説明が分かりやすい", "質問しやすい"]
        assert first.locator(".review-visit-times time").all_text_contents() == ["2026年10月21日 23:30", "2026年10月22日 00:30"]
        assert first.locator(".review-metrics dt").all_text_contents() == ["院内滞在", "費用"]
        assert first.locator(".review-metrics dd").all_text_contents() == ["60分", "1,840円"]
        assert cards.nth(1).locator(".review-metrics dd").all_text_contents() == ["30分", "0円"]
        assert cards.nth(1).locator(".review-note").inner_text() == "以前の形式の記録"
        assert cards.nth(1).locator(".record-hospital img").count() == 0
        assert not page.evaluate("Boolean(window.logInjected)")
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        assert cards.locator(".review-author, .record-hospital, .review-note, .review-metrics dd").evaluate_all(
            "elements => elements.every(element => element.scrollWidth <= element.clientWidth + 1)")
        expected = first.inner_html()
        first.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-log-card-{width}.png"))
        page.click('[data-record-view="day"]')
        page.click('[data-date="2026-10-21"]')
        assert page.locator("#dayDetails .personal-record").first.inner_html() == expected
        page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-day-log-{width}.png"))
        page.evaluate("state.emailVerification = {status: 'email_unverified', universityEmailVerified: false}; renderCalendar();")
        assert page.locator("#dayDetails .personal-record").first.locator(".review-verified").count() == 0
        assert page.locator("#dayDetails .personal-record").nth(1).locator(".review-verified").count() == 0
        assert errors == [], errors
        context.close()
    print("Personal log cards passed: shared layout, month/day parity, hidden identity and status, zero fee and escaping")


def check_fixed_university_registration(browser, url):
    for width in (320, 375, 1280):
        legacy = {"universityId": "F126310107564", "universityName": "同志社大学",
                  "grade": "4", "gender": "prefer_not_to_say", "nickname": "テスト"}
        with user_records.connect_records() as connection:
            connection.execute("INSERT INTO profiles VALUES (%s, %s)", ("test-user", json.dumps(legacy)))
        context = browser.new_context(viewport={"width": width, "height": 820}, timezone_id="Asia/Tokyo")
        context.route("https://unpkg.com/**", lambda route: route.abort())
        context.route("https://routing.openstreetmap.de/**", lambda route: route.abort())
        context.route("https://cdn.auth0.com/**", lambda route: route.fulfill(body=SDK, content_type="application/javascript"))
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("window.testLoggedIn = true;")
        page.goto(url)
        page.locator("#profileScreen").wait_for(state="visible")
        assert page.locator("#appContent").is_hidden()
        assert page.locator("#universitySearch, #universitySelect").count() == 0
        assert page.locator("#profileNickname").input_value() == "テスト"
        assert page.locator("#profileGrade").input_value() == "4"
        assert user_records.get_profile("test-user")["universityId"] == "F126310107564"
        page.click('#profileForm button[type="submit"]')
        page.locator("#appContent").wait_for(state="visible")
        assert "宮崎大学" in page.locator("#searchOrigin").inner_text()
        assert page.locator("#profileSummary").text_content() == "宮崎大学"
        search_at_nine(page)
        page.locator(".hospital-card").first.wait_for()
        assert "宮崎大学" in page.locator("#searchSummary").inner_text()
        assert page.locator("#accountStatus").text_content() == ""
        addresses = page.locator(".hospital-card .result-details > div:first-child dd").all_text_contents()
        assert addresses and all(address.startswith("宮崎県") for address in addresses)
        hospital_id = page.locator('.hospital-card [data-detail]').first.get_attribute("data-detail")
        page.locator('.hospital-card [data-detail]').first.click()
        page.locator("#screen-detail.active").wait_for()
        page.locator('#detail [data-plan]').click()
        page.fill("#manualArrivalAt", "2026-10-21T10:00")
        page.fill("#manualLeaveAt", "2026-10-21T10:45")
        page.fill("#feeAmount", "1200")
        page.select_option("#visitType", "初診")
        page.select_option("#reservationStatus", "予約あり")
        page.check('[data-positive-point][value="質問しやすい"]')
        page.fill("#sceneText", "動作確認用の口コミ")
        assert page.locator(".review-publication").is_visible()
        with patch("server.verified_email_university", return_value="doshisha"):
            page.click('#completionForm button[type="submit"]')
            page.locator("#screen-log.active").wait_for()
        record = user_records.list_records("test-user")[0]
        assert record["reviewSharing"]["published"] is True and record["stayMinutes"] == 45
        page.click('.tab[data-nav="search"]')
        search_at_nine(page)
        card = assert_hospital_estimate(page, hospital_id, 45)
        card.locator('[data-detail]').click()
        review = page.locator("#hospitalReviews .community-card.review-own")
        review.wait_for()
        assert review.locator(".review-verified").get_attribute("aria-label") == "同志社大学メール認証済み"
        assert review.locator(".review-verified").inner_text() == "認証済み"
        badge_image = review.locator(".review-verified img")
        assert badge_image.get_attribute("src") == "assets/universities/miyazaki-symbol.png"
        badge_image.evaluate("image => image.decode()")
        assert badge_image.evaluate("image => image.naturalWidth > 0")
        assert review.locator(".review-visit-times time").all_text_contents() == ["2026年10月21日 10:00", "10:45"]
        assert user_records.get_profile("test-user")["universityId"] == user_records.MIYAZAKI_UNIVERSITY_ID
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        review.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-doshisha-review-{width}.png"))
        assert errors == [], errors
        context.close()
        with user_records.connect_records() as connection:
            for table in ("profiles", "visits", "reviews"):
                connection.execute(f"DELETE FROM {table} WHERE user_id = %s", ("test-user",))
    print("Fixed Miyazaki registration checks passed: legacy profile, search origin, results, publication and email badge")


def check_email_badge_sync(browser, url):
    for status_name, university in (("verified", "miyazaki"), ("verified", "doshisha"),
                                    ("email_unverified", None), ("unsupported_domain", None),
                                    ("missing_email", None), ("unavailable", None)):
        user_records.save_profile("test-user", {"grade": "4", "gender": "prefer_not_to_say", "nickname": "ひなた"})
        user_records.save_record("test-user", {
            "id": "badge-sync", "hospitalId": "clinic:1", "hospitalName": "テスト病院", "department": "internal",
            "plannedAt": "2026-10-21T00:00:00Z", "arrivalAt": "2026-10-21T01:00:00Z", "leaveAt": "2026-10-21T01:30:00Z",
            "feeAmount": "1200", "reservationStatus": "予約あり", "waitingImpression": "未入力", "reviewVersion": 2,
            "visitType": "初診", "positivePoints": ["質問しやすい"], "sceneText": "メール認証前に投稿した口コミ",
            "reviewSharing": {"published": True},
        })
        context = browser.new_context(viewport={"width": 375, "height": 820})
        context.route("https://unpkg.com/**", lambda route: route.abort())
        context.route("https://cdn.auth0.com/**", lambda route: route.fulfill(body=SDK, content_type="application/javascript"))
        if status_name == "unavailable":
            context.route("**/api/email-verification", lambda route: route.fulfill(status=503,
                body='{"error":"Verification unavailable"}', content_type="application/json"))
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("window.testLoggedIn = true;")
        result = {"status": status_name, "universityEmailVerified": status_name == "verified", "verifiedEmailUniversity": university}
        with patch("server.email_verification_status", return_value=result):
            page.goto(url)
            page.locator("#appContent").wait_for(state="visible")
            page.wait_for_function("state.emailVerification && state.emailVerification.status !== 'checking'")
            page.click("#accountButton")
            if university:
                label = "宮崎大学メール認証済み" if university == "miyazaki" else "同志社大学メール認証済み"
                assert page.locator("#accountEmailBadge").inner_text() == label
                assert page.locator("#accountEmailBadge").is_visible()
                assert user_records.list_reviews("test-user", "clinic:1")[0]["universityEmailVerified"] is True
                page.click(".topbar h1")
                page.evaluate("""async () => {
                    state.selectedHospital = {id: 'clinic:1'};
                    document.querySelector('#detail').innerHTML = '<span id="reviewCount"></span><div id="hospitalReviews" class="community-feed"></div>';
                    navigate('detail'); await loadHospitalReviews(state.selectedHospital);
                }""")
                assert page.locator("#hospitalReviews .review-verified").get_attribute("aria-label") == label
            else:
                assert page.locator("#accountEmailBadge").is_hidden()
                messages = {"email_unverified": "メールアドレスが未確認", "unsupported_domain": "対象外",
                            "missing_email": "メール情報を取得できません", "unavailable": "確認に失敗"}
                assert messages[status_name] in page.locator("#accountEmailStatus").inner_text()
                assert not user_records.list_reviews("test-user", "clinic:1")[0]["universityEmailVerified"]
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-email-{status_name}-{university or 'none'}.png"))
            assert errors == [], errors
        context.close()
        with user_records.connect_records() as connection:
            for table in ("profiles", "visits", "reviews"):
                connection.execute(f"DELETE FROM {table} WHERE user_id = %s", ("test-user",))
    user_records.save_profile("test-user", {"grade": "4", "gender": "prefer_not_to_say", "nickname": "ひなた"})
    context = browser.new_context(viewport={"width": 320, "height": 820})
    context.route("https://unpkg.com/**", lambda route: route.abort())
    context.route("https://cdn.auth0.com/**", lambda route: route.fulfill(body=SDK, content_type="application/javascript"))
    pending = []
    context.route("**/api/email-verification", lambda route: pending.append(route))
    page = context.new_page()
    page.add_init_script("window.testLoggedIn = true;")
    page.goto(url)
    page.locator("#appContent").wait_for(state="visible")
    page.click("#accountButton")
    page.click("#logoutButton")
    page.locator("#loginScreen").wait_for(state="visible")
    assert pending
    pending[0].fulfill(body=json.dumps({"universityEmailVerified": True, "verifiedEmailUniversity": "doshisha",
                                       "status": "verified", "updatedReviews": 1}), content_type="application/json")
    page.wait_for_timeout(100)
    assert page.locator("#accountEmailBadge").text_content() == ""
    assert page.evaluate("state.emailVerification") is None
    context.close()
    with user_records.connect_records() as connection:
        connection.execute("DELETE FROM profiles WHERE user_id = %s", ("test-user",))
    print("Email badge checks passed: Miyazaki, Doshisha, old posts, failure reasons, outage and late logout response")


def check_manual_time_entry(browser, url):
    for width in (320, 375, 1280):
        context = browser.new_context(viewport={"width": width, "height": 820}, timezone_id="Asia/Tokyo")
        context.route("https://unpkg.com/**", lambda route: route.abort())
        context.route("https://cdn.auth0.com/**", lambda route: route.fulfill(body=SDK, content_type="application/javascript"))
        context.route("**/api/profile", lambda route: route.fulfill(body=json.dumps({"profile": {
            "nickname": "ひなた", "universityId": user_records.MIYAZAKI_UNIVERSITY_ID,
            "universityName": "宮崎大学", "grade": "4",
        }}), content_type="application/json"))
        saved = []
        def visits(route):
            if route.request.method == "POST":
                record = user_records.validate_record(json.loads(route.request.post_data))
                saved.append(record)
                route.fulfill(body=json.dumps({"visit": record}), content_type="application/json")
            else:
                route.fulfill(body='{"visits":[]}', content_type="application/json")
        context.route("**/api/visits", visits)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("window.testLoggedIn = true;")
        page.goto(url)
        page.locator("#appContent").wait_for(state="visible")
        page.evaluate("""() => {
            state.activeVisit = {id: 'manual-time-test', hospitalId: 'clinic:1', hospitalName: 'テスト病院',
                department: 'internal', plannedAt: new Date().toISOString(), arrivalAt: null, leaveAt: null,
                status: 'planned', feeAmount: '', reservationStatus: '未入力', waitingImpression: '未入力'};
            navigate('active'); renderActiveVisit();
        }""")
        assert "status =" not in page.locator("#screen-active").inner_text()
        assert "Web版MVP" not in page.locator("#screen-active").inner_text()
        assert page.locator('#manualTimeForm button').count() == 0
        assert page.locator("#manualLeaveAt").evaluate("input => input.required")
        assert page.locator("#manualTimeForm").evaluate("element => getComputedStyle(element).backgroundColor") == "rgba(0, 0, 0, 0)"
        assert "任意" not in page.locator("#manualTimeForm").inner_text()
        assert "必須" not in page.locator("#manualTimeForm").inner_text()
        page.fill("#manualArrivalAt", "2026-10-21T23:45")
        assert page.locator("#completionForm").count() == 0
        assert page.locator("#leaveButton").is_enabled()
        page.fill("#manualLeaveAt", "2026-10-22T00:15")
        assert page.locator("#manualStayMinutes").inner_text() == "30分"
        page.fill("#feeAmount", "0")
        page.select_option("#visitType", "初診")
        page.select_option("#reservationStatus", "予約なし")
        page.check('[data-positive-point][value="その他"]')
        page.fill("#sceneText", "時刻を変更してもこの文章を残す")
        page.fill("#manualLeaveAt", "2026-10-22T00:30")
        assert page.locator("#manualStayMinutes").inner_text() == "45分"
        page.locator("#activeVisit").screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-active-times-{width}.png"))
        assert page.locator("#feeAmount").input_value() == "0"
        assert page.locator("#sceneText").input_value() == "時刻を変更してもこの文章を残す"
        page.fill("#manualLeaveAt", "2026-10-21T23:00")
        page.click('#completionForm button[type="submit"]')
        assert "到着日時より後" in page.locator("#manualTimeError").inner_text()
        assert page.locator("#manualStayMinutes").inner_text() == "未確定"
        assert saved == []
        page.fill("#manualLeaveAt", "")
        assert page.locator("#completionForm").count() == 0
        assert not page.evaluate("synchronizeManualTimes(true)")
        assert "受診終了日時を入力" in page.locator("#manualTimeError").inner_text()
        assert saved == []
        page.fill("#manualLeaveAt", "2026-10-22T00:15")
        assert page.locator("#feeAmount").input_value() == "0"
        assert page.locator("#sceneText").input_value() == "時刻を変更してもこの文章を残す"
        page.reload()
        page.locator("#appContent").wait_for(state="visible")
        page.click('.tab[data-nav="active"]')
        assert page.locator("#manualStayMinutes").inner_text() == "30分"
        assert page.locator("#manualLeaveAt").input_value() == "2026-10-22T00:15"
        # Saving also reads the fields when the browser did not dispatch an input event.
        page.locator("#manualLeaveAt").evaluate("input => input.value = '2026-10-22T00:45'")
        page.click('#completionForm button[type="submit"]')
        page.locator("#screen-log.active").wait_for()
        assert len(saved) == 1 and saved[0]["stayMinutes"] == 60
        assert page.locator(".personal-record .review-metrics > div").filter(has_text="院内滞在").first.locator("dd").inner_text() == "60分"
        assert errors == [], errors
        context.close()
    print("Manual time checks passed: no apply, midnight, invalid range, cleared end, draft preservation and save sync")


def check_profile_submission(browser, url):
    context = browser.new_context(viewport={"width": 375, "height": 820})
    context.route("https://unpkg.com/**", lambda route: route.abort())
    context.route("https://cdn.auth0.com/**", lambda route: route.fulfill(
        body=SDK, content_type="application/javascript"))
    context.route("**/api/visits", lambda route: route.fulfill(
        body='{"visits":[]}', content_type="application/json"))
    pending_requests = []

    def profile_route(route):
        if route.request.method == "GET":
            route.fulfill(body='{"profile":null}', content_type="application/json")
        else:
            pending_requests.append(route)

    context.route("**/api/profile", profile_route)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script("window.testLoggedIn = true;")
    page.goto(url)
    page.locator("#profileScreen").wait_for(state="visible")
    submit = page.locator('#profileForm button[type="submit"]')
    status = page.locator("#profileStatus")
    submit.click()
    assert status.inner_text() == "ニックネームを入力してください。"
    page.fill("#profileNickname", "   ")
    submit.click()
    assert status.inner_text() == "ニックネームを入力してください。"
    page.fill("#profileNickname", "ひなた")
    submit.click()
    assert status.inner_text() == "学年を選択してください。"
    page.select_option("#profileGrade", "4")
    submit.click()
    assert status.inner_text() == "性別または「回答しない」を選択してください。"
    assert pending_requests == []
    page.select_option("#profileGender", "prefer_not_to_say")
    submit.click()
    page.wait_for_timeout(100)
    assert len(pending_requests) == 1
    assert submit.is_disabled()
    assert submit.inner_text() == "登録中…"
    assert page.locator("#profileForm").get_attribute("aria-busy") == "true"
    pending_requests[-1].fulfill(status=503, content_type="application/json",
                                 body=json.dumps({"error": "登録できませんでした。もう一度お試しください。"}))
    page.wait_for_function("!document.querySelector('#profileForm button[type=submit]').disabled")
    assert status.inner_text() == "登録できませんでした。もう一度お試しください。"
    assert page.locator("#profileNickname").input_value() == "ひなた"
    assert submit.inner_text() == "登録して始める"
    status.scroll_into_view_if_needed()
    page.screenshot(path=str(Path(tempfile.gettempdir()) / "clinic-profile-error-375.png"))
    submit.click()
    page.wait_for_timeout(100)
    assert len(pending_requests) == 2
    profile = pending_requests[-1].request.post_data_json
    assert profile["nickname"] == "ひなた"
    assert "universityId" not in profile and "universityName" not in profile
    profile["universityId"] = user_records.MIYAZAKI_UNIVERSITY_ID
    profile["universityName"] = "宮崎大学"
    old_profile = {key: value for key, value in profile.items() if key != "nickname"}
    pending_requests[-1].fulfill(content_type="application/json", body=json.dumps({"profile": old_profile}))
    page.wait_for_function("!document.querySelector('#profileForm button[type=submit]').disabled")
    assert "サーバーを再起動" in status.inner_text()
    assert page.locator("#appContent").is_hidden()
    submit.click()
    page.wait_for_timeout(100)
    assert len(pending_requests) == 3
    pending_requests[-1].fulfill(content_type="application/json", body=json.dumps({"profile": profile}))
    page.locator("#appContent").wait_for(state="visible")
    assert page.locator("#profileScreen").is_hidden()
    assert errors == [], errors
    context.close()
    print("Profile validation, pending save, retry and outdated server checks passed")


def main():
    with isolated_database(with_facilities=True), patch("server.authenticated_subject", return_value="test-user"), patch(
        "server.auth_config", return_value={"configured": True, "domain": "test.auth0.com",
                                            "clientId": "test-client", "audience": "test-api"}
    ), patch("server.verified_email_university", return_value="miyazaki"), patch(
        "server.email_verification_status", return_value={"universityEmailVerified": True,
        "verifiedEmailUniversity": "miyazaki", "status": "verified"}
    ):
        app = ThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
        thread = threading.Thread(target=app.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=os.environ.get("TEST_BROWSER_PATH"))
                for width in (320, 375, 1280):
                    context = browser.new_context(viewport={"width": width, "height": 640 if width == 320 else 820})
                    context.route("https://unpkg.com/**", lambda route: route.abort())
                    context.route("https://routing.openstreetmap.de/**", lambda route: route.abort())
                    context.route("https://cdn.auth0.com/**", lambda route: route.fulfill(
                        body=SDK, content_type="application/javascript"))
                    profile_requests = [0]
                    def profile_route(route):
                        profile_requests[0] += 1
                        if profile_requests[0] == 1:
                            route.fulfill(status=401, content_type="application/json",
                                          body=json.dumps({"error": "Expired token", "code": "token_expired"}))
                        else:
                            route.continue_()
                    context.route("**/api/profile", profile_route)
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.add_init_script("window.testLoggedIn = false;")
                    page.add_init_script("""navigator.geolocation.getCurrentPosition = () => {
                        window.geolocationRequested = true;
                        throw new Error('Location must not be requested');
                    };""")
                    url = f"http://127.0.0.1:{app.server_port}/"
                    page.goto(url)
                    page.locator("#loginButton:enabled").wait_for()
                    assert page.locator("#appContent").is_hidden()
                    assert page.locator("#loginScreen").is_visible()
                    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    assert page.locator("#loginScreen img").count() == 0
                    login_bounds = page.locator("#loginScreen .access-body").bounding_box()
                    viewport_height = page.viewport_size["height"]
                    assert abs(login_bounds["x"] + login_bounds["width"] / 2 - width / 2) < 2
                    assert abs(login_bounds["y"] + login_bounds["height"] / 2 - viewport_height / 2) < 2
                    assert page.locator("#signupButton").is_visible()
                    assert page.locator('#loginScreen [role="tablist"]').count() == 0
                    title_bounds = page.locator("#loginTitle").bounding_box()
                    button_bounds = page.locator("#loginButton").bounding_box()
                    signup_bounds = page.locator("#signupButton").bounding_box()
                    assert title_bounds["y"] + title_bounds["height"] < button_bounds["y"]
                    assert button_bounds["y"] + button_bounds["height"] < signup_bounds["y"]
                    assert button_bounds["width"] == signup_bounds["width"]
                    page.wait_for_function("""() => {
                        const style = (selector) => getComputedStyle(document.querySelector(selector));
                        const blue = style('.primary-button').backgroundColor;
                        return style('#loginTitle').color === blue
                            && style('#loginButton').backgroundColor === blue
                            && style('#signupButton').color === blue
                            && style('#signupButton').borderTopColor === blue;
                    }""")
                    page.evaluate("document.querySelector('#accountStatus').textContent = 'Test status';")
                    status_bounds = page.locator("#loginScreen .access-body").bounding_box()
                    assert abs(status_bounds["y"] - login_bounds["y"]) < 2
                    page.evaluate("document.querySelector('#accountStatus').textContent = '';")
                    page.set_viewport_size({"width": width, "height": viewport_height - 100})
                    resized_bounds = page.locator("#loginScreen .access-body").bounding_box()
                    assert abs(resized_bounds["y"] + resized_bounds["height"] / 2 - (viewport_height - 100) / 2) < 2
                    page.set_viewport_size({"width": width, "height": viewport_height})
                    page.click("#loginButton")
                    assert page.evaluate("window.loginOptions") == {}
                    page.click("#signupButton")
                    assert page.evaluate("window.loginOptions.authorizationParams.screen_hint") == "signup"
                    assert page.locator("#loginButton").is_visible()
                    page.evaluate("document.activeElement.blur()")
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-login-{width}.png"))
                    page.add_init_script("window.testLoggedIn = true;")
                    page.reload()
                    page.locator("#profileScreen").wait_for(state="visible")
                    assert page.evaluate("window.tokenRefreshes") == 1
                    assert page.locator("#appContent").is_hidden()
                    page.fill("#profileNickname", "ひなた")
                    assert page.locator("#universitySearch, #universitySelect, #universitySuggestions").count() == 0
                    assert page.locator(".profile-campus").inner_text() == "宮崎大学生専用"
                    page.select_option("#profileGrade", "4")
                    page.select_option("#profileGender", "prefer_not_to_say")
                    profile_bounds = page.locator("#profileScreen .access-body").bounding_box()
                    assert abs(profile_bounds["x"] + profile_bounds["width"] / 2 - width / 2) < 2
                    if profile_bounds["height"] + 56 <= viewport_height:
                        assert abs(profile_bounds["y"] + profile_bounds["height"] / 2 - viewport_height / 2) < 2
                    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    page.evaluate("window.scrollTo(0, 0)")
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-profile-{width}.png"))
                    page.click('#profileForm button[type="submit"]')
                    page.locator("#appContent").wait_for(state="visible")
                    assert page.locator("#originType").count() == 0
                    assert page.locator("#searchOrigin").inner_text() == "宮崎大学"
                    assert page.locator("#facilityType").count() == 0
                    assert page.locator("#visitStatus, .account-bar").count() == 0
                    title = page.locator(".topbar h1").bounding_box()
                    account = page.locator("#accountButton").bounding_box()
                    assert account["x"] > title["x"] + title["width"]
                    assert account["y"] < title["y"] + title["height"]
                    assert page.locator("#accountInitial").inner_text() == "ひ"
                    page.click("#accountButton")
                    assert page.locator("#accountButton").get_attribute("aria-expanded") == "true"
                    assert page.locator("#accountNickname").inner_text() == "ひなた"
                    assert page.locator("#profileSummary").inner_text() == "宮崎大学"
                    page.wait_for_function("document.querySelector('#logoutButton img').naturalWidth > 0")
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-account-menu-{width}.png"))
                    page.keyboard.press("Escape")
                    assert page.locator("#accountMenu").is_hidden()
                    assert page.locator("#accountButton").evaluate("element => element === document.activeElement")
                    page.press("#accountButton", "ArrowDown")
                    assert page.locator("#settingsButton").evaluate("element => element === document.activeElement")
                    page.click(".topbar h1")
                    assert page.locator("#accountMenu").is_hidden()
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-search-{width}.png"))
                    page.evaluate("document.querySelector('#locationStatus')?.remove()")
                    context.route("**/api/university-origin", lambda route: route.fulfill(
                        status=503, body='{"error":"Location unavailable"}', content_type="application/json"))
                    page.click('#searchForm button[type="submit"]')
                    page.wait_for_function("document.querySelector('#accountStatus').textContent === 'Location unavailable'")
                    assert page.locator('#searchForm button[type="submit"]').is_enabled()
                    assert page.locator("#screen-search.active").is_visible()
                    context.unroute("**/api/university-origin")
                    search_at_nine(page)
                    page.wait_for_function("document.querySelector('#searchSummary').textContent.includes('宮崎大学')")
                    assert "09:00出発" in page.locator("#searchSummary").inner_text()
                    assert page.locator("#accountStatus").inner_text() == ""
                    page.locator(".hospital-card").first.wait_for()
                    assert page.locator(".hospital-card dt").filter(has_text="実測データ").count() == 0
                    assert page.locator(".hospital-card .result-highlight strong").first.inner_text().endswith("ごろ")
                    page.wait_for_function("!document.querySelector('#routeStatus').classList.contains('loading')")
                    assert not page.evaluate("Boolean(window.geolocationRequested)")
                    addresses = page.locator(".hospital-card .result-details > div:first-child dd").all_text_contents()
                    assert addresses and all(address.startswith("宮崎県") for address in addresses)
                    assert not page.locator(".hospital-card .department-label").filter(has_text="薬局").count()
                    hospital_id = page.locator('.hospital-card [data-plan]').first.get_attribute("data-plan")
                    kind = page.locator('.hospital-card .department-label').first.inner_text()
                    first_card = assert_hospital_estimate(page, hospital_id, 60 if kind == "病院" else 35)
                    assert first_card.locator('.result-details > div').filter(has_text="費用目安").locator("dd").inner_text() == "データなし"
                    page.locator('.hospital-card [data-plan]').first.click()
                    page.click("#arrivalButton")
                    page.click("#leaveButton")
                    page.fill("#manualArrivalAt", "2026-10-21T10:00")
                    page.fill("#manualLeaveAt", "2026-10-21T10:30")
                    assert page.locator("#manualStayMinutes").inner_text() == "30分"
                    note = '診察は1841円。\n説明が丁寧でした。<img src=x onerror="window.reviewInjected=true">'
                    assert page.locator("#waitingMinutes").count() == 0
                    assert page.locator("#feeAmount").evaluate("input => input.required && input.validity.valueMissing")
                    page.click('#completionForm button[type="submit"]')
                    assert page.locator("#screen-active.active").count() == 1
                    assert len(user_records.list_records("test-user")) == 0
                    page.fill("#feeAmount", "0")
                    assert page.locator("#feeAmount").evaluate("input => input.checkValidity()")
                    assert not page.locator("#visitType").evaluate("input => input.checkValidity()")
                    page.select_option("#visitType", "初診")
                    assert not page.locator("#reservationStatus").evaluate("input => input.checkValidity()")
                    page.select_option("#reservationStatus", "予約なし")
                    assert not page.locator("[data-positive-point]").first.evaluate("input => input.checkValidity()")
                    page.click('#completionForm button[type="submit"]')
                    assert len(user_records.list_records("test-user")) == 0
                    page.check('[data-positive-point][value="特になし・分からない"]')
                    assert page.locator("#completionForm").evaluate("form => form.checkValidity()")
                    page.fill("#feeAmount", "1841")
                    page.fill("#sceneText", note)
                    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-completion-{width}.png"), full_page=True)
                    page.reload()
                    page.locator("#appContent").wait_for(state="visible")
                    page.click('.tab[data-nav="active"]')
                    assert page.locator("#sceneText").input_value() == note
                    assert page.locator("#feeAmount").input_value() == "1841"
                    assert page.locator("#visitType").input_value() == "初診"
                    assert page.locator("#reservationStatus").input_value() == "予約なし"
                    assert page.locator('[data-positive-point][value="特になし・分からない"]').is_checked()
                    page.click('#completionForm button[type="submit"]')
                    page.locator("#screen-log.active").wait_for()
                    assert user_records.list_records("test-user")[0]["stayMinutes"] == 30
                    assert page.locator("#monthDetails .review-metrics > div").filter(has_text="院内滞在").first.locator("dd").inner_text() == "30分"
                    assert page.locator("#monthDetails .review-note").first.inner_text() == note
                    assert page.locator("#monthDetails .review-note img").count() == 0
                    first_review = user_records.list_reviews("test-user", hospital_id)[0]
                    assert first_review["note"] == "" and first_review["sceneText"] == note
                    assert first_review["stayMinutes"] == 30
                    assert first_review["arrivalAt"] == user_records.list_records("test-user")[0]["arrivalAt"]
                    assert first_review["leaveAt"] == user_records.list_records("test-user")[0]["leaveAt"]
                    assert user_records.list_records("test-user")[0]["reviewSharing"]["published"] is True
                    assert page.locator("#monthDetails [data-unpublish]").count() == 0
                    assert "公開中" not in page.locator("#monthDetails").inner_text()
                    # Seed a historical private record; the UI no longer offers withdrawal.
                    user_records.unpublish_review("test-user", user_records.list_records("test-user")[0]["id"])
                    assert user_records.list_reviews("test-user", hospital_id) == []
                    page.reload()
                    page.locator("#appContent").wait_for(state="visible")
                    page.click('.tab[data-nav="log"]')
                    assert page.locator("#monthDetails .review-note").first.inner_text() == note
                    page.click('.tab[data-nav="search"]')
                    search_at_nine(page)
                    private_card = assert_hospital_estimate(page, hospital_id, 30)
                    assert private_card.locator('.result-details > div').filter(has_text="費用目安").locator("dd").inner_text() == "データなし"
                    page.locator(f'.hospital-card [data-detail="{hospital_id}"]').click()
                    page.locator("#screen-detail.active").wait_for()
                    assert "滞在時間データ" not in page.locator("#detail").inner_text()
                    assert "実測データ" not in page.locator("#detail").inner_text()
                    assert page.locator(".detail-panel .stats-empty, .detail-panel .stats-list").count() == 0
                    assert page.locator(".detail-panel .metric").filter(has_text="施設区分").count() == 0
                    department_metric = page.locator(".detail-panel .metric").filter(has_text="診療科")
                    assert department_metric.count() == 1
                    assert "内科" in department_metric.locator("strong").inner_text()
                    assert page.locator(".detail-panel aside p").filter(has_text="診療科").count() == 0
                    page.locator(".detail-panel").screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-detail-{width}.png"))
                    assert page.locator(".detail-reviews .review-note").first.inner_text() == note
                    assert page.locator(".detail-reviews .review-note img").count() == 0
                    assert not page.evaluate("Boolean(window.reviewInjected)")
                    assert page.locator("[data-unpublish]").count() == 0
                    user_records.save_profile("other-reviewer", {"universityId": user_records.MIYAZAKI_UNIVERSITY_ID,
                                                                  "grade": "2", "gender": "female", "nickname": "こもれび"})
                    user_records.save_record("other-reviewer", {
                        "id": "other-review", "hospitalId": hospital_id, "hospitalName": "Hospital",
                        "department": "internal", "plannedAt": "2026-10-17T00:00:00Z",
                        "arrivalAt": "2026-10-17T00:10:00Z", "leaveAt": "2026-10-17T00:35:00Z",
                        "feeAmount": "1200", "reservationStatus": "予約なし", "waitingImpression": "スムーズ",
                        "note": "", "reviewVersion": 2, "nickname": "こもれび", "visitType": "再診", "waitingMinutes": 10,
                        "positivePoints": ["特になし・分からない"], "sceneText": "授業の前に受診できました。", "adviceText": "",
                        "reviewSharing": {"published": True},
                    }, verified_email_university="doshisha")
                    page.locator('#detail [data-plan]').click()
                    page.click("#arrivalButton")
                    page.click("#leaveButton")
                    page.fill("#manualArrivalAt", "2026-10-21T11:00")
                    page.fill("#manualLeaveAt", "2026-10-21T12:00")
                    assert page.locator("#publishReview").count() == 0
                    assert page.locator("#shareVisitTimes, .review-time-consent").count() == 0
                    assert "受診日時（月日・到着〜終了時刻）と一緒に" in page.locator(".review-publication-note").inner_text()
                    page.fill("#feeAmount", "2000")
                    page.select_option("#visitType", "初診")
                    page.select_option("#reservationStatus", "予約なし")
                    assert page.locator("#waitingMinutes").count() == 0
                    page.check('[data-positive-point][value="説明が分かりやすい"]')
                    page.check('[data-positive-point][value="その他"]')
                    page.check('[data-positive-point][value="特になし・分からない"]')
                    assert not page.locator('[data-positive-point][value="説明が分かりやすい"]').is_checked()
                    assert not page.locator('[data-positive-point][value="その他"]').is_checked()
                    page.check('[data-positive-point][value="質問しやすい"]')
                    assert not page.locator('[data-positive-point][value="特になし・分からない"]').is_checked()
                    page.check('[data-positive-point][value="説明が分かりやすい"]')
                    page.check('[data-positive-point][value="その他"]')
                    page.fill("#sceneText", "薬の使い方を紙に書いて説明してくれた。")
                    page.fill("#adviceText", "支払いは現金だった。会計は少し待ちました。")
                    assert page.locator("#publishReview").count() == 0
                    assert page.locator("#shareVisitTimes, .review-time-consent").count() == 0
                    assert page.locator("#reviewNickname, #verifyUniversityEmail, [data-review-field], #reviewPreview").count() == 0
                    assert page.locator("#accountNickname").text_content() == "ひなた"
                    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    page.locator('.review-publication').scroll_into_view_if_needed()
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-review-form-{width}.png"))
                    # Preserve the older fee choice, while always publishing visit times.
                    page.evaluate("""() => {
                        const key = 'campusClinicActiveVisit:test-user';
                        const draft = JSON.parse(localStorage.getItem(key));
                        draft.reviewSharing.showFee = false;
                        draft.reviewSharing.showVisitTimes = false;
                        localStorage.setItem(key, JSON.stringify(draft));
                    }""")
                    page.reload()
                    page.locator("#appContent").wait_for(state="visible")
                    page.click('.tab[data-nav="active"]')
                    assert page.locator("#publishReview").count() == 0
                    assert page.locator("#shareVisitTimes").count() == 0
                    assert page.evaluate("state.activeVisit.reviewSharing.showVisitTimes") is True
                    assert page.locator("#reviewNickname, #verifyUniversityEmail, [data-review-field], #reviewPreview").count() == 0
                    assert page.locator("#feeAmount").input_value() == "2000"
                    assert page.locator('[data-positive-point][value="その他"]').is_checked()
                    assert page.locator("#adviceText").input_value() == "支払いは現金だった。会計は少し待ちました。"
                    page.click('#completionForm button[type="submit"]')
                    page.locator("#screen-log.active").wait_for()
                    assert page.locator("#monthDetails [data-unpublish]").count() == 0
                    assert "公開中" not in page.locator("#monthDetails").inner_text()
                    page.click('.tab[data-nav="search"]')
                    search_at_nine(page)
                    average_card = assert_hospital_estimate(page, hospital_id, 39)
                    assert average_card.locator('.result-details > div').filter(has_text="費用目安").locator("dd").inner_text() == "平均 1,200円"
                    average_card.locator(".result-highlight").scroll_into_view_if_needed()
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-average-stay-{width}.png"))
                    page.locator(f'.hospital-card [data-detail="{hospital_id}"]').click()
                    page.wait_for_function("document.querySelector('#hospitalReviews').textContent.includes('授業の前に受診できました。')")
                    assert page.locator(".metric").filter(has_text="費用").locator("strong").inner_text() == "平均 1,200円"
                    assert page.evaluate("feeEstimate({averageFeeAmount: 0})") == "平均 0円"
                    assert page.evaluate("feeEstimate({averageFeeAmount: 10000000})") == "平均 10,000,000円"
                    own_review = page.locator("#hospitalReviews .community-card.review-own")
                    assert "学部4年" in own_review.inner_text()
                    assert "ひなた" in own_review.inner_text()
                    assert "初診" in own_review.inner_text()
                    assert own_review.locator(".review-verified").get_attribute("aria-label") == "宮崎大学メール認証済み"
                    assert "次に行く学生へ" in own_review.inner_text()
                    assert "会計は少し待ちました。" in own_review.inner_text()
                    assert "その他" in own_review.locator(".review-point-list").inner_text()
                    assert own_review.locator("dt").filter(has_text="待ち時間").count() == 0
                    assert own_review.locator("dt").filter(has_text="費用").count() == 0
                    assert own_review.locator(".review-author strong").inner_text() == "ひなた"
                    assert own_review.locator(".review-avatar").inner_text() == "ひ"
                    assert own_review.locator(".review-month").count() == 0
                    assert own_review.locator(".review-visit-times time").all_text_contents() == ["2026年10月21日 11:00", "12:00"]
                    assert own_review.locator(".review-body").bounding_box()["y"] < own_review.locator(".review-metrics").bounding_box()["y"]
                    own_review.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-review-card-{width}.png"))
                    other_review = page.locator("#hospitalReviews .community-card:not(.review-own):not(.review-private)")
                    assert "学部2年" in other_review.inner_text()
                    assert "1,200" in other_review.inner_text()
                    assert other_review.locator(".review-month").count() == 0
                    assert other_review.locator(".review-visit-times time").all_text_contents() == ["2026年10月17日 09:10", "09:35"]
                    assert "こもれび" in other_review.inner_text()
                    assert other_review.locator(".review-verified").get_attribute("aria-label") == "同志社大学メール認証済み"
                    other_review.scroll_into_view_if_needed()
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-reviews-{width}.png"))
                    page.click('.tab[data-nav="log"]')
                    assert page.locator("#monthDetails [data-unpublish]").count() == 0
                    own_record = next(record for record in user_records.list_records("test-user")
                                      if record["reviewSharing"]["published"])
                    user_records.unpublish_review("test-user", own_record["id"])
                    reviews = user_records.list_reviews("test-user", hospital_id)
                    assert len(reviews) == 1 and not reviews[0]["isOwnRecord"]
                    assert len(user_records.list_records("test-user")) == 2
                    other_record = user_records.list_records("other-reviewer")[0]
                    user_records.save_record("other-reviewer", {**other_record, "id": "other-review-2", "feeAmount": "1801"})
                    page.click('.tab[data-nav="search"]')
                    search_at_nine(page)
                    fee_card = page.locator(f'.hospital-card:has([data-plan="{hospital_id}"])')
                    fee_card.wait_for()
                    fee_field = fee_card.locator('.result-details > div').filter(has_text="費用目安")
                    assert fee_field.locator("dd").inner_text() == "平均 1,501円"
                    fee_field.scroll_into_view_if_needed()
                    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-average-fee-{width}.png"))
                    user_records.unpublish_review("other-reviewer", "other-review-2")
                    page.click('[data-nav="search"].results-back')
                    search_at_nine(page)
                    assert fee_field.locator("dd").inner_text() == "平均 1,200円"
                    page.click('[data-nav="search"].results-back')
                    context.route("**/api/facilities?**", lambda route: route.fulfill(
                        status=503, body='{"error":"Facility database unavailable"}', content_type="application/json"))
                    page.click('#searchForm button[type="submit"]')
                    page.locator("#routeStatus.warning").wait_for()
                    assert "施設APIに接続できません" in page.locator("#routeStatus").inner_text()
                    assert page.locator(".hospital-card").count() == 0
                    assert not page.evaluate("Boolean(window.geolocationRequested)")
                    assert page.locator("#profileScreen").is_hidden()
                    page.click("#accountButton")
                    page.click("#logoutButton")
                    page.locator("#loginScreen").wait_for(state="visible")
                    page.locator("#loginButton:enabled").wait_for()
                    assert page.locator("#appContent").is_hidden()
                    assert page.evaluate("window.logoutChecks") == 1
                    assert page.locator("#monthDetails .personal-record").count() == 0
                    assert errors == [], errors
                    context.close()
                    with user_records.connect_records() as connection:
                        connection.execute("DELETE FROM profiles")
                        connection.execute("DELETE FROM visits")
                        connection.execute("DELETE FROM reviews")
                check_auth_redirect(browser, f"http://127.0.0.1:{app.server_port}/")
                check_profile_submission(browser, f"http://127.0.0.1:{app.server_port}/")
                check_account_logout(browser, f"http://127.0.0.1:{app.server_port}/")
                check_review_layout(browser, f"http://127.0.0.1:{app.server_port}/")
                check_personal_log_layout(browser, f"http://127.0.0.1:{app.server_port}/")
                check_manual_time_entry(browser, f"http://127.0.0.1:{app.server_port}/")
                check_fixed_university_registration(browser, f"http://127.0.0.1:{app.server_port}/")
                check_email_badge_sync(browser, f"http://127.0.0.1:{app.server_port}/")
                check_account_settings(browser, f"http://127.0.0.1:{app.server_port}/")
                browser.close()
                print("Onboarding checks passed at 320px, 375px and 1280px")
                print(f"Screenshots: {tempfile.gettempdir()}/clinic-profile-375.png")
        finally:
            app.shutdown()
            app.server_close()
            thread.join()


if __name__ == "__main__":
    main()
