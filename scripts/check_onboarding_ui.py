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
  getUser: async () => ({sub: 'test-user', name: 'Test User'}),
  getTokenSilently: async (options) => {
    if (options.cacheMode === 'off') window.tokenRefreshes = (window.tokenRefreshes || 0) + 1;
    return 'test-token';
  },
  loginWithRedirect: async (options) => { window.loginOptions = options || {}; },
  logout: async () => {},
}; } };
"""


def check_auth_redirect(browser, url):
    for scenario in ("success", "callback_error", "api_rejected", "login_required"):
        context = browser.new_context(viewport={"width": 375, "height": 820})
        context.route("https://unpkg.com/**", lambda route: route.abort())
        context.route("https://cdn.auth0.com/**", lambda route: route.fulfill(
            body=SDK, content_type="application/javascript"))
        context.route("**/api/visits", lambda route: route.fulfill(
            body='{"visits":[]}', content_type="application/json"))
        profile = {"universityName": "Test University"}
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
            assert page.evaluate("window.sessionChecks || 0") == 0
            page.add_init_script("window.testLoggedIn = true;")
            page.reload()
            page.locator("#appContent").wait_for(state="visible")
            assert page.evaluate("window.sessionChecks") == 1
            assert page.evaluate("window.callbackChecks || 0") == 0
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


def main():
    with tempfile.TemporaryDirectory() as directory, patch.object(
        user_records, "RECORDS_DATABASE", Path(directory) / "records.sqlite3"
    ), patch("server.authenticated_subject", return_value="test-user"), patch(
        "server.auth_config", return_value={"configured": True, "domain": "test.auth0.com",
                                            "clientId": "test-client", "audience": "test-api"}
    ):
        app = ThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
        thread = threading.Thread(target=app.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=os.environ.get("TEST_BROWSER_PATH"))
                for width in (320, 375, 1280):
                    context = browser.new_context(viewport={"width": width, "height": 640 if width == 320 else 820})
                    context.grant_permissions(["geolocation"])
                    context.set_geolocation({"latitude": 35.0299, "longitude": 135.7608})
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
                    page.fill("#universitySearch", "宮崎大学")
                    option = page.get_by_role("option", name="宮崎大学（宮崎）", exact=True)
                    option.wait_for()
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-universities-{width}.png"))
                    page.press("#universitySearch", "ArrowDown")
                    page.press("#universitySearch", "Enter")
                    assert page.locator("#universitySelect").input_value() == "F145110111523"
                    page.fill("#universitySearch", "同志社")
                    assert page.locator("#universitySelect").input_value() == ""
                    page.fill("#universitySearch", "宮崎大学")
                    page.get_by_role("option", name="宮崎大学（宮崎）", exact=True).click()
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
                    assert page.locator("#originType option").count() == 2
                    assert page.locator("#originType").input_value() == "university"
                    assert page.locator("#facilityType").count() == 0
                    page.evaluate("document.querySelector('#locationStatus')?.remove()")
                    context.route("**/api/university-origin", lambda route: route.fulfill(
                        status=503, body='{"error":"Location unavailable"}', content_type="application/json"))
                    page.click('#searchForm button[type="submit"]')
                    page.wait_for_function("document.querySelector('#accountStatus').textContent === 'Location unavailable'")
                    assert page.locator('#searchForm button[type="submit"]').is_enabled()
                    assert page.locator("#screen-search.active").is_visible()
                    context.unroute("**/api/university-origin")
                    page.click('#searchForm button[type="submit"]')
                    page.wait_for_function("document.querySelector('#searchSummary').textContent.includes('宮崎大学')")
                    assert page.locator("#accountStatus").inner_text() == ""
                    page.locator(".hospital-card").first.wait_for()
                    page.click('[data-nav="search"].results-back')
                    page.select_option("#originType", "current")
                    page.click('#searchForm button[type="submit"]')
                    page.wait_for_function("document.querySelector('#searchSummary').textContent.startsWith('現在地から')")
                    page.wait_for_function("!document.querySelector('#routeStatus').classList.contains('loading')")
                    assert not page.locator(".hospital-card .department-label").filter(has_text="薬局").count()
                    hospital_id = page.locator('.hospital-card [data-plan]').first.get_attribute("data-plan")
                    page.locator('.hospital-card [data-plan]').first.click()
                    page.click("#arrivalButton")
                    page.click("#leaveButton")
                    note = '診察は1841円。\n説明が丁寧でした。<img src=x onerror="window.reviewInjected=true">'
                    page.fill("#feeAmount", "1841")
                    page.fill("#visitNote", note)
                    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-completion-{width}.png"), full_page=True)
                    page.reload()
                    page.locator("#appContent").wait_for(state="visible")
                    page.click('.tab[data-nav="active"]')
                    assert page.locator("#visitNote").input_value() == note
                    assert page.locator("#feeAmount").input_value() == "1841"
                    page.click('#completionForm button[type="submit"]')
                    page.locator("#screen-log.active").wait_for()
                    assert page.locator("#monthDetails .review-note").first.inner_text() == note
                    assert page.locator("#monthDetails .review-note img").count() == 0
                    page.reload()
                    page.locator("#appContent").wait_for(state="visible")
                    page.click('.tab[data-nav="log"]')
                    assert page.locator("#monthDetails .review-note").first.inner_text() == note
                    page.click('.tab[data-nav="search"]')
                    page.select_option("#originType", "current")
                    page.click('#searchForm button[type="submit"]')
                    page.locator(f'.hospital-card [data-detail="{hospital_id}"]').click()
                    page.locator("#screen-detail.active").wait_for()
                    assert page.locator(".detail-reviews .review-note").first.inner_text() == note
                    assert page.locator(".detail-reviews .review-note img").count() == 0
                    assert not page.evaluate("Boolean(window.reviewInjected)")
                    assert page.locator("[data-unpublish]").count() == 0
                    user_records.save_profile("other-reviewer", {"universityId": user_records.MIYAZAKI_UNIVERSITY_ID,
                                                                  "grade": "2", "gender": "female"})
                    user_records.save_record("other-reviewer", {
                        "id": "other-review", "hospitalId": hospital_id, "hospitalName": "Hospital",
                        "department": "internal", "plannedAt": "2026-10-17T00:00:00Z",
                        "arrivalAt": "2026-10-17T00:10:00Z", "leaveAt": "2026-10-17T00:35:00Z",
                        "feeAmount": "1200", "reservationStatus": "予約なし", "waitingImpression": "スムーズ",
                        "note": "授業の前に受診できました。", "reviewSharing": {"published": True},
                    })
                    page.locator('#detail [data-plan]').click()
                    page.click("#arrivalButton")
                    page.click("#leaveButton")
                    assert not page.locator("#publishReview").is_checked()
                    page.fill("#feeAmount", "2000")
                    page.fill("#visitNote", "説明が丁寧で安心できました。")
                    page.check("#publishReview")
                    page.uncheck('[data-review-field="showFee"]')
                    assert "学部3〜4年" in page.locator("#reviewPreview").inner_text()
                    assert "2,000" not in page.locator("#reviewPreview").inner_text()
                    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    page.locator("#reviewPreview").scroll_into_view_if_needed()
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-review-preview-{width}.png"))
                    page.reload()
                    page.locator("#appContent").wait_for(state="visible")
                    page.click('.tab[data-nav="active"]')
                    assert page.locator("#publishReview").is_checked()
                    assert not page.locator('[data-review-field="showFee"]').is_checked()
                    page.click('#completionForm button[type="submit"]')
                    page.locator("#screen-log.active").wait_for()
                    assert page.locator("#monthDetails [data-unpublish]").count() == 1
                    page.click('.tab[data-nav="search"]')
                    page.select_option("#originType", "current")
                    page.click('#searchForm button[type="submit"]')
                    page.locator(f'.hospital-card [data-detail="{hospital_id}"]').click()
                    page.wait_for_function("document.querySelector('#hospitalReviews').textContent.includes('授業の前に受診できました。')")
                    own_review = page.locator(".community-card").filter(has_text="自分の口コミ・公開中")
                    assert "学部3〜4年" in own_review.inner_text()
                    assert own_review.locator("dt").filter(has_text="費用").count() == 0
                    other_review = page.locator(".community-card").filter(has_text="宮大生の口コミ")
                    assert "学部1〜2年" in other_review.inner_text()
                    assert "1,200" in other_review.inner_text()
                    assert "2026" not in other_review.inner_text()
                    other_review.scroll_into_view_if_needed()
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / f"clinic-reviews-{width}.png"))
                    page.click('.tab[data-nav="log"]')
                    page.locator("#monthDetails [data-unpublish]").click()
                    page.wait_for_function("!document.querySelector('#monthDetails [data-unpublish]')")
                    reviews = user_records.list_reviews("test-user", hospital_id)
                    assert len(reviews) == 1 and not reviews[0]["isOwnRecord"]
                    assert len(user_records.list_records("test-user")) == 2
                    assert page.locator("#profileScreen").is_hidden()
                    page.click("#logoutButton")
                    page.locator("#loginScreen").wait_for(state="visible")
                    assert page.locator("#appContent").is_hidden()
                    assert errors == [], errors
                    context.close()
                    with user_records.connect_records() as connection:
                        connection.execute("DELETE FROM profiles")
                        connection.execute("DELETE FROM visits")
                        connection.execute("DELETE FROM reviews")
                check_auth_redirect(browser, f"http://127.0.0.1:{app.server_port}/")
                browser.close()
                print("Onboarding checks passed at 320px, 375px and 1280px")
                print(f"Screenshots: {tempfile.gettempdir()}/clinic-profile-375.png")
        finally:
            app.shutdown()
            app.server_close()
            thread.join()


if __name__ == "__main__":
    main()
