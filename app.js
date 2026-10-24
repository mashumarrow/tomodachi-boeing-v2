const departments = {
  internal: "内科",
  dermatology: "皮膚科",
  eye: "眼科",
  ent: "耳鼻咽喉科",
  gynecology: "婦人科",
  pharmacy: "薬局",
};

const facilityTypeLabels = {
  hospital: "病院",
  clinic: "診療所",
  pharmacy: "薬局",
};

const transportSpeed = {
  walk: 1,
  bike: 0.3,
  car: 0.15,
};

const transportationLabels = {
  walk: "徒歩",
  bike: "自転車",
  car: "車",
};

const osrmServers = {
  walk: "https://routing.openstreetmap.de/routed-foot",
  bike: "https://routing.openstreetmap.de/routed-bike",
  car: "https://routing.openstreetmap.de/routed-car",
};

let lastOsrmRequestAt = 0;

let hospitals = [];

const state = {
  view: "list",
  recordView: "month",
  selectedHospital: null,
  activeVisit: null,
  calendarDate: new Date(),
  selectedDate: dateKey(new Date()),
  visits: [],
  authClient: null,
  authReady: false,
  loggingOut: false,
  savingSettings: false,
  deletingAccount: false,
  settingsReturnScreen: "search",
  user: null,
  emailVerification: null,
  emailVerificationCheckedAt: 0,
  profile: null,
  reviewFeeds: new Map(),
  universityLocation: null,
  routeTimes: new Map(),
  routeCache: new Map(),
  resultMap: null,
  resultMapBounds: null,
};

const $ = (selector) => document.querySelector(selector);
const signedOutKey = "campusClinicSignedOut";

function explicitlySignedOut() {
  try {
    return sessionStorage.getItem(signedOutKey) === "1";
  } catch {
    return false;
  }
}

function rememberSignedOut(signedOut) {
  try {
    if (signedOut) sessionStorage.setItem(signedOutKey, "1");
    else sessionStorage.removeItem(signedOutKey);
  } catch {
    // SDK logout still runs when browser storage is unavailable.
  }
}

function setAccountMenu(open, restoreFocus = false) {
  const show = Boolean(open && state.user && !$("#appContent").hidden);
  $("#accountMenu").hidden = !show;
  $("#accountButton").setAttribute("aria-expanded", String(show));
  if (show) void refreshEmailVerification();
  if (!show && restoreFocus) $("#accountButton").focus();
}

function updateAccessScreen() {
  const canEnter = Boolean(
    state.authReady &&
    state.user &&
    state.profile?.nickname?.trim() &&
    canShareReviews(),
  );
  $("#appContent").hidden = !canEnter;
  $("#loginScreen").hidden = !state.authReady || Boolean(state.user);
  $("#profileScreen").hidden = !state.authReady || !state.user || canEnter;
  if (canEnter) {
    const nickname = state.profile.nickname;
    $("#accountNickname").textContent = nickname;
    $("#profileSummary").textContent = state.profile.universityName;
    $("#accountInitial").textContent = Array.from(nickname)[0];
    $("#accountButton").setAttribute("aria-label", `${nickname}のアカウント`);
    let picture = "";
    try {
      const url = new URL(state.user.picture);
      if (url.protocol === "https:") picture = url.href;
    } catch {
      // A missing or invalid picture uses the nickname initial.
    }
    const avatar = $("#accountAvatar");
    if (picture && avatar.getAttribute("src") !== picture) avatar.src = picture;
    if (!picture) avatar.removeAttribute("src");
    avatar.hidden = !picture || (avatar.complete && avatar.naturalWidth === 0);
    $("#accountInitial").hidden = !avatar.hidden;
    $("#searchOrigin").textContent =
      state.universityLocation?.label || "宮崎大学";
  } else {
    setAccountMenu(false);
    $("#accountNickname").textContent = "";
    $("#profileSummary").textContent = "";
    $("#accountInitial").textContent = "";
    $("#accountInitial").hidden = false;
    $("#accountAvatar").hidden = true;
    $("#accountAvatar").removeAttribute("src");
    $("#accountButton").setAttribute("aria-label", "アカウント");
  }
  renderEmailVerificationStatus();
}

async function openProfileRegistration() {
  updateAccessScreen();
  $("#profileStatus").textContent = "";
  const profile = state.profile;
  $("#profileNickname").value = profile?.nickname || "";
  $("#profileGrade").value = profile?.grade || "";
  $("#profileGender").value = profile?.gender || "";
  $("#accountStatus").textContent = "";
}

async function enterApplication() {
  const data = await authorizedFetch("/api/visits");
  state.visits = data.visits;
  loadActiveVisit();
  selectLatestVisit();
  renderActiveVisit();
  renderCalendar();
  updateAccessScreen();
  $("#accountStatus").textContent = "";
  void refreshEmailVerification();
}

function openAccountSettings() {
  if (
    !state.user ||
    !state.profile ||
    state.savingSettings ||
    state.deletingAccount
  )
    return;
  const currentScreen = $(".screen.active")?.id.replace("screen-", "");
  if (currentScreen !== "settings")
    state.settingsReturnScreen = currentScreen || "search";
  for (const field of ["Grade", "Gender"]) {
    $(`#settings${field}`).replaceChildren(
      ...Array.from($(`#profile${field}`).options, (option) =>
        option.cloneNode(true),
      ),
    );
    $(`#settings${field}`).value = state.profile[field.toLowerCase()];
  }
  $("#settingsNickname").value = state.profile.nickname;
  $("#settingsNickname").setCustomValidity("");
  $("#settingsStatus").textContent = "";
  $("#settingsStatus").dataset.error = "false";
  navigate("settings");
  $("#settingsTitle").focus({ preventScroll: true });
}

async function saveAccountSettings(event) {
  event.preventDefault();
  const subject = state.user?.sub;
  if (!subject || state.savingSettings || state.deletingAccount) return;
  const form = event.target;
  $("#settingsNickname").setCustomValidity(
    $("#settingsNickname").value.trim()
      ? ""
      : "ニックネームを入力してください。",
  );
  if (!form.reportValidity()) return;
  const value = {
    nickname: $("#settingsNickname").value.trim(),
    grade: $("#settingsGrade").value,
    gender: $("#settingsGender").value,
  };
  state.savingSettings = true;
  $("#settingsFields").disabled = true;
  $("#settingsSaveButton").disabled = true;
  $("#withdrawButton").disabled = true;
  $("#settingsSaveButton").textContent = "保存中...";
  $("#settingsStatus").textContent = "";
  form.setAttribute("aria-busy", "true");
  try {
    const data = await authorizedFetch("/api/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(value),
    });
    if (state.user?.sub !== subject) return;
    if (!data.profile?.nickname?.trim())
      throw new Error("プロフィールを保存できませんでした。");
    state.profile = data.profile;
    updateAccessScreen();
    $("#settingsStatus").dataset.error = "false";
    $("#settingsStatus").textContent = "変更を保存しました。";
  } catch (error) {
    if (state.user?.sub !== subject) return;
    $("#settingsStatus").dataset.error = "true";
    $("#settingsStatus").textContent = error.message;
    if ($("#appContent").hidden)
      $("#accountStatus").textContent = error.message;
  } finally {
    if (state.user?.sub === subject) {
      state.savingSettings = false;
      $("#settingsFields").disabled = false;
      $("#settingsSaveButton").disabled = false;
      $("#withdrawButton").disabled = false;
      $("#settingsSaveButton").textContent = "変更を保存";
      form.removeAttribute("aria-busy");
    }
  }
}

function renderEmailVerificationStatus() {
  const status = state.user ? state.emailVerification : null;
  const labels = new Map([
    ["miyazaki", "宮崎大学"],
    ["doshisha", "同志社大学"],
  ]);
  const university = labels.get(status?.verifiedEmailUniversity);
  const verified = status?.universityEmailVerified === true && university;
  $("#accountEmailBadge").hidden = !verified;
  $("#accountEmailBadge").textContent = verified
    ? `${university}メール認証済み`
    : "";
  const messages = {
    checking: "大学メールを確認中です。",
    email_unverified:
      "メールアドレスが未確認です。確認メールのリンクを開き、再ログインしてください。",
    unsupported_domain: "このメールドメインは認証バッジの対象外です。",
    missing_email: "メール情報を取得できませんでした。再ログインしてください。",
    identity_mismatch:
      "メールの本人確認ができませんでした。再ログインしてください。",
    error:
      "大学メールの確認に失敗しました。アカウント欄を開き直すと再確認します。",
  };
  $("#accountEmailStatus").textContent = verified
    ? ""
    : messages[status?.status] || "";
}

async function refreshEmailVerification() {
  if (
    !state.user ||
    state.emailVerification?.status === "checking" ||
    Date.now() - state.emailVerificationCheckedAt < 30000
  )
    return;
  const subject = state.user.sub;
  state.emailVerification = { status: "checking" };
  renderEmailVerificationStatus();
  try {
    let data = await authorizedFetch("/api/email-verification", {
      method: "POST",
    });
    if (data.status === "missing_email") {
      await state.authClient.getTokenSilently({ cacheMode: "off" });
      data = await authorizedFetch("/api/email-verification", {
        method: "POST",
      });
    }
    if (state.user?.sub !== subject) return;
    state.emailVerification = data;
    state.emailVerificationCheckedAt = Date.now();
    renderCalendar();
    if (data.updatedReviews > 0) {
      state.reviewFeeds.clear();
      if (state.selectedHospital && $("#hospitalReviews")) {
        await loadHospitalReviews(state.selectedHospital);
      }
    }
  } catch {
    if (state.user?.sub !== subject) return;
    state.emailVerification = { status: "error" };
  }
  if (state.user?.sub === subject) renderEmailVerificationStatus();
}

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[character],
  );
}

async function authorizedFetch(path, options = {}) {
  if (!state.user || !state.authClient)
    throw new Error("ログインしてください。");
  const subject = state.user.sub;
  const request = async (refresh) => {
    const token = await state.authClient.getTokenSilently(
      refresh ? { cacheMode: "off" } : {},
    );
    if (state.user?.sub !== subject)
      throw new Error("ログイン状態が変更されました。");
    return fetch(path, {
      ...options,
      headers: { ...options.headers, Authorization: `Bearer ${token}` },
    });
  };
  let response = await request(false);
  if (response.status === 401) {
    try {
      response = await request(true);
    } catch {
      // Preserve the original API error when silent renewal is unavailable.
    }
  }
  const data = await response.json();
  if (state.user?.sub !== subject)
    throw new Error("ログイン状態が変更されました。");
  if (!response.ok) {
    if (response.status === 401) {
      state.user = null;
      state.emailVerification = null;
      state.emailVerificationCheckedAt = 0;
      state.profile = null;
      state.visits = [];
      state.activeVisit = null;
      updateAccessScreen();
    } else if (["profile_required", "miyazaki_required"].includes(data.code)) {
      state.profile = null;
      updateAccessScreen();
    }
    const message = data.error || "記録を取得・保存できませんでした。";
    const error = new Error(data.code ? `${message} (${data.code})` : message);
    error.status = response.status;
    throw error;
  }
  return data;
}

async function initializeAuth() {
  updateAccessScreen();
  try {
    const response = await fetch("/api/auth-config");
    if (response.status === 404)
      throw new Error(
        "認証APIがありません。python server.py で起動したURLを開いてください。",
      );
    if (!response.ok) throw new Error("ログイン設定を読み込めませんでした。");
    const config = await response.json();
    if (!config.configured) {
      throw new Error(
        "ログイン設定が未完了です。.env のAuth0設定を確認してサーバーを再起動してください。",
      );
    }
    if (!window.auth0) throw new Error("ログイン機能を読み込めませんでした。");
    state.authClient = new auth0.Auth0Client({
      domain: config.domain,
      clientId: config.clientId,
      authorizationParams: {
        redirect_uri: `${location.origin}/`,
        audience: config.audience,
        scope: "openid profile email",
      },
    });
    const parameters = new URLSearchParams(location.search);
    if (
      parameters.has("state") &&
      (parameters.has("code") || parameters.has("error"))
    ) {
      try {
        await state.authClient.handleRedirectCallback();
        rememberSignedOut(false);
      } finally {
        const cleanUrl = new URL(location.href);
        [
          "code",
          "state",
          "error",
          "error_description",
          "iss",
          "session_state",
        ].forEach((key) => cleanUrl.searchParams.delete(key));
        history.replaceState(
          {},
          document.title,
          `${cleanUrl.pathname}${cleanUrl.search}${cleanUrl.hash}`,
        );
      }
    } else {
      if (explicitlySignedOut()) {
        $("#accountStatus").textContent = "";
        return;
      }
      try {
        await state.authClient.checkSession();
      } catch (error) {
        if (
          ![
            "login_required",
            "consent_required",
            "interaction_required",
            "missing_refresh_token",
          ].includes(error.error)
        )
          throw error;
      }
    }
    if (await state.authClient.isAuthenticated()) {
      state.user = await state.authClient.getUser();
      $("#accountStatus").textContent =
        state.user.name || state.user.email || "ログイン中";
      const data = await authorizedFetch("/api/profile");
      state.profile = data.profile;
      if (state.profile?.nickname?.trim() && canShareReviews())
        await enterApplication();
      else await openProfileRegistration();
    } else {
      $("#accountStatus").textContent = "";
    }
  } catch (error) {
    $("#accountStatus").textContent = error.message;
  } finally {
    state.authReady = true;
    $("#loginButton").disabled = !state.authClient;
    $("#signupButton").disabled = !state.authClient;
    updateAccessScreen();
  }
  renderActiveVisit();
  renderCalendar();
}

function minutesFromTime(value) {
  const [hours, minutes] = value.split(":").map(Number);
  return hours * 60 + minutes;
}

function timeFromDate(date) {
  return date.toTimeString().slice(0, 5);
}

function formatClockMinutes(totalMinutes) {
  const dayOffset = Math.floor(totalMinutes / (24 * 60));
  const normalized = ((totalMinutes % (24 * 60)) + 24 * 60) % (24 * 60);
  const hours = Math.floor(normalized / 60);
  const minutes = normalized % 60;
  const clock = `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
  return dayOffset > 0 ? `翌日 ${clock}` : clock;
}

function dateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatCurrency(value) {
  if (!Number.isFinite(value)) return "データなし";
  return `${value.toLocaleString("ja-JP")}円`;
}

function feeEstimate(hospital) {
  if (
    !Number.isFinite(hospital.averageFeeAmount) ||
    hospital.averageFeeAmount < 0
  )
    return "データなし";
  return `平均 ${formatCurrency(hospital.averageFeeAmount)}`;
}

function calculateDistanceKm(origin, destination) {
  const toRadians = (value) => (value * Math.PI) / 180;
  const latitudeDelta = toRadians(destination.latitude - origin.latitude);
  const longitudeDelta = toRadians(destination.longitude - origin.longitude);
  const a =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(toRadians(origin.latitude)) *
      Math.cos(toRadians(destination.latitude)) *
      Math.sin(longitudeDelta / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function getSelectedOrigin() {
  return state.universityLocation;
}

function getFacilityDistance(hospital) {
  const origin = getSelectedOrigin();
  if (!origin) return Infinity;
  return calculateDistanceKm(origin, hospital);
}

function getTravelDurations(hospital) {
  const route = state.routeTimes.get(hospital.id);
  if (route) return route;
  const transportation = $("#transportation").value;
  const distance = getFacilityDistance(hospital);
  const walkingMinutes = (distance / 4.5) * 60;
  const estimate = Math.max(
    3,
    Math.round(walkingMinutes * transportSpeed[transportation]),
  );
  return { outbound: estimate, inbound: estimate, source: "estimate" };
}

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function requestOsrmTable(url) {
  const elapsed = Date.now() - lastOsrmRequestAt;
  if (elapsed < 1100) await wait(1100 - elapsed);
  lastOsrmRequestAt = Date.now();
  const response = await fetch(url);
  if (!response.ok) throw new Error(`OSRM ${response.status}`);
  const data = await response.json();
  if (data.code !== "Ok")
    throw new Error(data.message || "OSRMから経路を取得できませんでした");
  return data;
}

async function loadOsrmRoutes(hospitalResults) {
  if (!hospitalResults.length) return 0;
  const origin = getSelectedOrigin();
  const transportation = $("#transportation").value;
  const server = osrmServers[transportation];
  const cachePrefix = `${transportation}:${origin.latitude.toFixed(5)},${origin.longitude.toFixed(5)}`;
  const cachedRoutes = hospitalResults.map(({ hospital }) =>
    state.routeCache.get(`${cachePrefix}:${hospital.id}`),
  );
  if (cachedRoutes.every(Boolean)) {
    hospitalResults.forEach(({ hospital }, index) =>
      state.routeTimes.set(hospital.id, cachedRoutes[index]),
    );
    return hospitalResults.length;
  }
  const coordinates = [
    origin,
    ...hospitalResults.map(({ hospital }) => hospital),
  ]
    .map((point) => `${point.longitude},${point.latitude}`)
    .join(";");
  const destinationIndexes = hospitalResults
    .map((_, index) => index + 1)
    .join(";");
  const sourceIndexes = destinationIndexes;
  const baseUrl = `${server}/table/v1/driving/${coordinates}`;

  try {
    const outbound = await requestOsrmTable(
      `${baseUrl}?sources=0&destinations=${destinationIndexes}&annotations=duration,distance&skip_waypoints=true`,
    );
    const inbound = await requestOsrmTable(
      `${baseUrl}?sources=${sourceIndexes}&destinations=0&annotations=duration,distance&skip_waypoints=true`,
    );

    hospitalResults.forEach(({ hospital }, index) => {
      const outboundSeconds = outbound.durations?.[0]?.[index];
      const inboundSeconds = inbound.durations?.[index]?.[0];
      if (Number.isFinite(outboundSeconds) && Number.isFinite(inboundSeconds)) {
        const route = {
          outbound: Math.max(1, Math.ceil(outboundSeconds / 60)),
          inbound: Math.max(1, Math.ceil(inboundSeconds / 60)),
          source: "osrm",
        };
        state.routeTimes.set(hospital.id, route);
        state.routeCache.set(`${cachePrefix}:${hospital.id}`, route);
      }
    });
    return state.routeTimes.size;
  } catch (error) {
    console.warn("OSRM route lookup failed", error);
    return 0;
  }
}

function getSearchContext() {
  const startTime = $("#startTime").value;
  const start = minutesFromTime(startTime);
  let returnBy = minutesFromTime($("#returnTime").value);
  if (returnBy < start) returnBy += 24 * 60;
  return {
    department: $("#department").value,
    start,
    returnBy,
  };
}

function setDefaultSearchTimes() {
  const now = new Date();
  const returnTime = new Date(now.getTime() + 90 * 60 * 1000);
  $("#startTime").value = timeFromDate(now);
  $("#returnTime").value = timeFromDate(returnTime);
}

function updateLocationStatus(message) {
  const status = $("#locationStatus");
  if (status) status.textContent = message;
}

async function ensureSearchOrigin() {
  if (getSelectedOrigin()) return true;
  const button = $(".search-submit");
  const previousLabel = button.textContent;
  button.disabled = true;
  button.textContent = "大学の所在地を取得しています";
  updateLocationStatus("位置情報を確認しています…");
  try {
    const data = await authorizedFetch("/api/university-origin");
    state.universityLocation = data.origin;
    $("#searchOrigin").textContent = data.origin.label;
    updateLocationStatus(
      `${data.origin.label} / ${data.origin.matchedAddress || data.origin.address}`,
    );
    $("#accountStatus").textContent = "";
    return true;
  } catch (error) {
    updateLocationStatus(error.message);
    $("#accountStatus").textContent = error.message;
    return false;
  } finally {
    button.disabled = false;
    button.textContent = previousLabel;
  }
}

async function loadNearbyFacilities() {
  const origin = getSelectedOrigin();
  const context = getSearchContext();
  const parameters = new URLSearchParams({
    latitude: String(origin.latitude),
    longitude: String(origin.longitude),
    radius: "12",
    limit: "200",
    department: context.department,
  });

  try {
    const data = await authorizedFetch(`/api/facilities?${parameters}`);
    hospitals = Array.isArray(data.facilities)
      ? data.facilities.filter(
          (facility) =>
            ["hospital", "clinic"].includes(facility.type) &&
            facility.address?.startsWith("宮崎県"),
        )
      : [];
    return true;
  } catch (error) {
    console.warn("Facility API lookup failed", error);
    if (error.status === 401 || error.status === 403) throw error;
    hospitals = [];
    return false;
  }
}

function evaluateHospital(hospital) {
  const context = getSearchContext();
  const travel = getTravelDurations(hospital);
  const stay =
    Number.isFinite(hospital.averageStayMinutes) &&
    hospital.averageStayMinutes > 0
      ? hospital.averageStayMinutes
      : hospital.medianWait;
  const total = travel.outbound + travel.inbound + stay;
  const returnAt = context.start + total;
  const remaining = context.returnBy - context.start - total;
  const fit =
    remaining >= 30
      ? "good"
      : remaining >= 10
        ? "warn"
        : remaining >= 0
          ? "tight"
          : "bad";
  return { ...travel, stay, total, returnAt, remaining, fit };
}

function fitLabel(fit) {
  if (fit === "good") return "余裕あり";
  if (fit === "warn") return "間に合いそう";
  if (fit === "tight") return "余裕少なめ";
  return "厳しそう";
}

function fitClass(fit) {
  if (fit === "good") return "good";
  if (fit === "bad") return "bad";
  return "warn";
}

function returnMessage(estimate) {
  if (estimate.remaining >= 30)
    return `予定まで${estimate.remaining}分の余裕があります`;
  if (estimate.remaining >= 0) return `予定まで残り${estimate.remaining}分です`;
  return `予定を約${Math.abs(estimate.remaining)}分超える見込みです`;
}

function matchingHospitals() {
  const { department } = getSearchContext();
  return hospitals
    .filter((hospital) => {
      if (getFacilityDistance(hospital) > 12) return false;
      return (
        ["hospital", "clinic"].includes(hospital.type) &&
        hospital.departments.includes(department)
      );
    })
    .map((hospital) => ({ hospital, estimate: evaluateHospital(hospital) }))
    .sort((a, b) => b.estimate.remaining - a.estimate.remaining)
    .slice(0, 1000);
}

function createMapPopup(hospital, estimate) {
  const popup = document.createElement("div");
  popup.className = "map-popup";

  const name = document.createElement("strong");
  name.textContent = hospital.name;
  popup.appendChild(name);

  const returnTime = document.createElement("span");
  returnTime.textContent = `${formatClockMinutes(estimate.returnAt)}ごろに戻れます`;
  popup.appendChild(returnTime);

  const detailButton = document.createElement("button");
  detailButton.className = "map-popup-button";
  detailButton.type = "button";
  detailButton.textContent = "詳しく見る";
  detailButton.addEventListener("click", () => renderDetail(hospital.id));
  popup.appendChild(detailButton);
  return popup;
}

function renderResultMap(results) {
  const mapSurface = $("#mapSurface");
  if (state.resultMap) {
    state.resultMap.remove();
    state.resultMap = null;
  }

  if (!window.L) {
    mapSurface.innerHTML =
      '<div class="map-error">地図を読み込めませんでした。インターネット接続を確認してください。</div>';
    return;
  }

  mapSurface.innerHTML = "";
  const origin = getSelectedOrigin();
  const map = L.map(mapSurface, { zoomControl: true });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  const points = [[origin.latitude, origin.longitude]];
  L.circleMarker([origin.latitude, origin.longitude], {
    radius: 8,
    color: "#ffffff",
    weight: 3,
    fillColor: "#1769e0",
    fillOpacity: 1,
  })
    .addTo(map)
    .bindTooltip(origin.label, { direction: "top" });

  results.forEach(({ hospital, estimate }) => {
    const point = [hospital.latitude, hospital.longitude];
    points.push(point);
    L.marker(point).addTo(map).bindPopup(createMapPopup(hospital, estimate));
  });

  state.resultMap = map;
  state.resultMapBounds = L.latLngBounds(points);
  map.fitBounds(state.resultMapBounds, { padding: [28, 28], maxZoom: 15 });
}

function refreshResultMapSize() {
  if (!state.resultMap) return;
  window.setTimeout(() => {
    state.resultMap.invalidateSize();
    if (state.resultMapBounds) {
      state.resultMap.fitBounds(state.resultMapBounds, {
        padding: [28, 28],
        maxZoom: 15,
      });
    }
  }, 0);
}

async function renderResults() {
  state.routeTimes.clear();
  const context = getSearchContext();
  const startLabel = `${$("#startTime").value}出発`;
  const targetLabel = departments[context.department];
  const originLabel =
    getSelectedOrigin()?.label || state.profile.universityName;
  $("#searchSummary").textContent =
    `${originLabel}から / ${targetLabel} / ${startLabel} / ${$("#returnTime").value}まで / ${transportationLabels[$("#transportation").value]}`;

  $("#results").innerHTML =
    '<div class="route-loading">周辺施設を検索しています</div>';
  const loadedFromApi = await loadNearbyFacilities();
  let results = matchingHospitals();
  $("#results-title").textContent = `検索結果 ${results.length}件`;
  if (!results.length) {
    if (state.resultMap) {
      state.resultMap.remove();
      state.resultMap = null;
      state.resultMapBounds = null;
    }
    $("#routeStatus").className = "route-status warning";
    $("#routeStatus").textContent = loadedFromApi
      ? "大学から12km以内に条件に合う宮崎県の病院・診療所がありません"
      : "施設APIに接続できません。python server.pyで起動してください";
    $("#results").innerHTML = `
      <div class="result-empty">
        <h3>条件に合う施設がありません</h3>
        <p class="muted">診療科や戻り時刻を変更して、もう一度検索してください。</p>
      </div>
    `;
    $("#mapSurface").innerHTML = "";
    return;
  }

  $("#results").innerHTML = results
    .map(
      ({ hospital, estimate }) => `
    <article class="hospital-card">
      <header class="result-card-header">
        <div class="result-name">
          <span class="department-label">${facilityTypeLabels[hospital.type] || departments[context.department]}</span>
          <div class="hospital-title">
          <h3>${hospital.name}</h3>
          </div>
        </div>
        <span class="badge ${fitClass(estimate.fit)}">${fitLabel(estimate.fit)}</span>
      </header>

      <div class="result-highlight">
        <span>戻ってこられる時刻の目安</span>
        <strong>${formatClockMinutes(estimate.returnAt)}<small>ごろ</small></strong>
        <p class="duration-summary">往復・受診の合計 約${estimate.total}分</p>
        <p class="return-message ${fitClass(estimate.fit)}">${returnMessage(estimate)}</p>
      </div>

      <div class="time-breakdown" aria-label="所要時間の内訳">
        <div><span>行き</span><strong>${estimate.outbound}分</strong></div>
        <span class="breakdown-separator">＋</span>
        <div><span>院内滞在</span><strong>${estimate.stay}分</strong></div>
        <span class="breakdown-separator">＋</span>
        <div><span>帰り</span><strong>${estimate.inbound}分</strong></div>
      </div>

      <dl class="result-details">
        <div>
          <dt>場所</dt>
          <dd>${hospital.address}</dd>
        </div>
        <div>
          <dt>診療時間</dt>
          <dd>${hospital.open}</dd>
        </div>
        <div>
          <dt>費用目安</dt>
          <dd>${feeEstimate(hospital)}</dd>
        </div>
      </dl>

      <div class="card-actions">
        <button class="secondary-button" type="button" data-detail="${hospital.id}">詳しく見る</button>
        <button class="primary-button" type="button" data-plan="${hospital.id}">この施設に行く</button>
      </div>
    </article>
  `,
    )
    .join("");

  renderResultMap(results);
}

function renderDetail(hospitalId) {
  const hospital = hospitals.find((item) => item.id === hospitalId);
  const estimate = evaluateHospital(hospital);
  const departmentNames = hospital.departments
    .map((key) => departments[key] || key)
    .join(" / ");
  state.selectedHospital = hospital;
  if (canShareReviews())
    state.reviewFeeds.set(hospitalId, { posts: [], loading: true });
  $("#detail").innerHTML = `
    <article class="detail-panel">
      <div class="detail-grid">
        <div>
          <div class="hospital-title">
            <h2 id="detail-title">${hospital.name}</h2>
            <span class="badge ${fitClass(estimate.fit)}">${fitLabel(estimate.fit)}</span>
          </div>
          <p class="detail-copy">${hospital.address}</p>
          <div class="metrics">
            <div class="metric"><span>移動</span><strong>往復${estimate.outbound + estimate.inbound}分</strong></div>
            <div class="metric"><span>目安</span><strong>合計${estimate.total}分</strong></div>
            <div class="metric"><span>診療科</span><strong>${escapeHtml(departmentNames || "掲載なし")}</strong></div>
            <div class="metric"><span>費用</span><strong>${feeEstimate(hospital)}</strong></div>
          </div>
          <div class="detail-actions">
            <button class="primary-button" type="button" data-plan="${hospital.id}">この施設に行く</button>
            <a class="secondary-button" href="${hospital.maps}" target="_blank" rel="noreferrer">Google Mapsで見る</a>
            ${hospital.website ? `<a class="secondary-button" href="${hospital.website}" target="_blank" rel="noreferrer">公式サイトを見る</a>` : ""}
          </div>
        </div>
        <aside>
          <p class="muted">出発地点から直線距離: ${getFacilityDistance(hospital).toFixed(2)}km</p>
        </aside>
      </div>
    </article>
    <section class="detail-reviews" aria-labelledby="reviews-title">
      <div class="detail-section-heading">
        <div>
          <span class="section-kicker">宮大生の受診体験</span>
          <h3 id="reviews-title">口コミ・自分の記録</h3>
        </div>
        <strong id="reviewCount">${getHospitalReviews(hospital).length}件</strong>
      </div>
      <div class="community-feed" id="hospitalReviews">
        ${renderReviewCards(hospital)}
      </div>
    </section>
  `;
  navigate("detail");
  if (canShareReviews()) loadHospitalReviews(hospital);
}

function planVisit(hospitalId) {
  if (!state.user) {
    $("#accountStatus").textContent =
      "受診記録を作成するにはログインしてください。";
    $("#loginButton").focus();
    return;
  }
  const hospital = hospitals.find((item) => item.id === hospitalId);
  const now = new Date();
  state.activeVisit = {
    id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
    hospitalId,
    hospitalName: hospital.name,
    department:
      hospital.type === "pharmacy" ? "pharmacy" : $("#department").value,
    status: "planned",
    plannedAt: now.toISOString(),
    arrivalAt: null,
    leaveAt: null,
    feeAmount: "",
    reservationStatus: "未入力",
    waitingImpression: "未入力",
    note: "",
    reviewSharing: {
      published: canShareReviews(),
      showGrade: true,
      showReservation: true,
      showDuration: true,
      showFee: true,
    },
  };
  saveActiveVisit();
  navigate("active");
  renderActiveVisit();
}

function renderActiveVisit() {
  const visit = state.activeVisit;
  if (!visit) {
    $("#activeVisit").innerHTML = `
      <div class="active-panel">
        <h3>進行中の受診はありません</h3>
        <p class="muted">検索結果から「行く」を選ぶと、ここに計測フローが表示されます。</p>
      </div>
    `;
    return;
  }

  $("#activeVisit").innerHTML = `
    <div class="active-panel">
      <div>
        <h3>${escapeHtml(visit.hospitalName)}</h3>
      </div>
      <details class="manual-time-panel" open>
        <summary>到着・終了時刻を手入力</summary>
        <div class="manual-time-form" id="manualTimeForm">
          <label>病院への到着日時
            <input id="manualArrivalAt" type="datetime-local" value="${toDatetimeLocal(visit.arrivalAt)}" required />
          </label>
          <label>受診終了日時
            <input id="manualLeaveAt" type="datetime-local" value="${toDatetimeLocal(visit.leaveAt)}" required />
          </label>
          <p class="form-error" id="manualTimeError" aria-live="polite"></p>
          <div class="manual-duration"><span>院内滞在</span><output id="manualStayMinutes" aria-live="polite">${visit.leaveAt ? `${stayMinutes(visit)}分` : "未確定"}</output></div>
        </div>
      </details>
      <div class="card-actions">
        <button class="primary-button" type="button" id="arrivalButton" ${visit.arrivalAt ? "disabled" : ""}>現在時刻で到着</button>
        <button class="secondary-button" type="button" id="leaveButton" ${!visit.arrivalAt || visit.leaveAt ? "disabled" : ""}>現在時刻で終了</button>
      </div>
      <div id="completionFields">${visit.leaveAt ? completionFields(visit) : ""}</div>
    </div>
  `;
  if (visit.leaveAt) {
    readCompletionDraft();
    updateReviewValidation();
  }
}

function completionFields(visit) {
  const points = visit.positivePoints || [];
  return `
    <form class="completion-form" id="completionForm">
      <fieldset class="review-step">
        <legend><span>1</span>受診条件を選ぶ<span class="review-required">必須</span></legend>
        <div class="review-condition-grid">
          <label>初診・再診<select id="visitType" required>${["未入力", "初診", "再診", "分からない"].map((type) => `<option ${visit.visitType === type ? "selected" : ""}>${type}</option>`).join("")}</select></label>
          <label>予約の有無<select id="reservationStatus" required>${["未入力", "予約あり", "予約なし"].map((value) => `<option ${visit.reservationStatus === value ? "selected" : ""}>${value}</option>`).join("")}</select></label>
          <label>費用（円・必須）<input id="feeAmount" type="number" min="0" max="10000000" step="1" value="${escapeHtml(visit.feeAmount ?? "")}" placeholder="1840" required /></label>
        </div>
      </fieldset>
      <fieldset class="review-step review-positive-points">
        <legend><span>2</span>よかった点・助かったことはあった？<span class="review-required">必須</span></legend>
        ${["説明が分かりやすい", "質問しやすい", "受付が丁寧", "プライバシーへの配慮", "その他", "特になし・分からない"].map((point) => `<label class="review-check"><input type="checkbox" data-positive-point value="${point}" ${points.includes(point) ? "checked" : ""} />${point}</label>`).join("")}
      </fieldset>
      <fieldset class="review-step">
        <legend><span>3</span>そう感じた場面を一言<span class="review-optional">任意</span></legend>
        <textarea id="sceneText" aria-label="そう感じた場面を一言" rows="3" maxlength="2000" placeholder="薬の使い方を紙に書いて説明してくれた">${escapeHtml(visit.sceneText ?? visit.note ?? "")}</textarea>
      </fieldset>
      <fieldset class="review-step">
        <legend><span>4</span>次に行く学生へ伝えたいこと<span class="review-optional">任意</span></legend>
        <textarea id="adviceText" aria-label="次に行く学生へ伝えたいこと" rows="3" maxlength="1000" placeholder="初診は時間に余裕を持つとよさそう。気になった点も書けます。">${escapeHtml(visit.adviceText || "")}</textarea>
      </fieldset>
      ${canShareReviews() ? reviewSharingFields() : ""}
      <button class="primary-button" type="submit">記録を保存</button>
    </form>
  `;
}

function canShareReviews() {
  return state.profile?.universityId === "F145110111523";
}

function profileGradeLabel() {
  const grade = state.profile?.grade || "";
  if (/^[1-6]$/.test(grade)) return `学部${grade}年`;
  if (/^master[1-2]$/.test(grade)) return `修士${grade.slice(-1)}年`;
  if (/^doctor[1-3]$/.test(grade)) return `博士${grade.slice(-1)}年`;
  return "学生";
}

function reviewSharingFields() {
  return `
    <div class="review-publication">
      <p class="review-publication-note">保存した口コミは、受診日時（月日・到着〜終了時刻）と一緒に宮大生に公開されます。日時からあなたの受診が推測される可能性があります。本文に本名や個人情報を含めないでください。</p>
    </div>
  `;
}

function readCompletionDraft() {
  const visit = state.activeVisit;
  visit.feeAmount = $("#feeAmount").value;
  visit.reservationStatus = $("#reservationStatus").value;
  visit.reviewVersion = 2;
  visit.visitType = $("#visitType").value;
  visit.positivePoints = [
    ...document.querySelectorAll("[data-positive-point]:checked"),
  ].map((input) => input.value);
  visit.sceneText = $("#sceneText").value;
  visit.adviceText = $("#adviceText").value;
  visit.nickname = state.profile?.nickname || "";
  visit.note = "";
  visit.reviewSharing = {
    ...visit.reviewSharing,
    published: canShareReviews(),
    showVisitTimes: true,
  };
}

function updateReviewValidation() {
  const visit = state.activeVisit;
  const sharing = visit.reviewSharing || {};
  $("#visitType").setCustomValidity(
    visit.visitType === "未入力" ? "初診・再診を選択してください。" : "",
  );
  $("#reservationStatus").setCustomValidity(
    visit.reservationStatus === "未入力"
      ? "予約の有無を選択してください。"
      : "",
  );
  $("[data-positive-point]").setCustomValidity(
    !visit.positivePoints.length
      ? "よかった点、または「特になし・分からない」を選択してください。"
      : "",
  );
  $('#completionForm button[type="submit"]').textContent = sharing.published
    ? "記録を保存して口コミを投稿"
    : "記録を保存";
}

function markArrival() {
  state.activeVisit.arrivalAt = new Date().toISOString();
  state.activeVisit.arrivalMethod = "button";
  state.activeVisit.status = "measuring";
  saveActiveVisit();
  renderActiveVisit();
}

function markLeave() {
  if (!synchronizeManualTimes()) return;
  state.activeVisit.leaveAt = new Date().toISOString();
  state.activeVisit.leaveMethod = "button";
  state.activeVisit.status = "completed";
  saveActiveVisit();
  renderActiveVisit();
}

function synchronizeManualTimes(requireLeave = false) {
  const visit = state.activeVisit;
  if (!visit) return false;

  const arrivalInput = $("#manualArrivalAt");
  const leaveInput = $("#manualLeaveAt");
  const arrivalValue = arrivalInput.value;
  const leaveValue = leaveInput.value;
  const error = $("#manualTimeError");
  const output = $("#manualStayMinutes");
  // Keep button timestamps at full precision until their displayed values change.
  const arrivalAt = new Date(
    arrivalValue === toDatetimeLocal(visit.arrivalAt)
      ? visit.arrivalAt
      : arrivalValue,
  );
  const leaveAt = leaveValue
    ? new Date(
        leaveValue === toDatetimeLocal(visit.leaveAt)
          ? visit.leaveAt
          : leaveValue,
      )
    : null;
  const invalid = (message) => {
    error.textContent = message;
    output.textContent = "未確定";
    return false;
  };

  if (
    !arrivalValue ||
    !arrivalInput.validity.valid ||
    Number.isNaN(arrivalAt.getTime())
  ) {
    return invalid("到着日時を入力してください。");
  }
  if (
    leaveValue &&
    (!leaveInput.validity.valid ||
      Number.isNaN(leaveAt.getTime()) ||
      leaveAt < arrivalAt)
  ) {
    return invalid("終了日時は到着日時より後にしてください。");
  }
  if (requireLeave && !leaveAt)
    return invalid("受診終了日時を入力してください。");

  if ($("#completionForm")) readCompletionDraft();
  const arrivalIso = arrivalAt.toISOString();
  const leaveIso = leaveAt ? leaveAt.toISOString() : null;
  if (arrivalIso !== visit.arrivalAt) visit.arrivalMethod = "manual";
  if (leaveIso !== visit.leaveAt) visit.leaveMethod = leaveAt ? "manual" : null;
  visit.arrivalAt = arrivalIso;
  visit.leaveAt = leaveIso;
  visit.status = leaveAt ? "completed" : "measuring";
  visit.stayMinutes = stayMinutes(visit);
  error.textContent = "";
  output.textContent = leaveAt ? `${visit.stayMinutes}分` : "未確定";
  $("#arrivalButton").disabled = Boolean(visit.arrivalAt);
  $("#leaveButton").disabled = !visit.arrivalAt || Boolean(visit.leaveAt);
  if (leaveAt && !$("#completionForm")) {
    $("#completionFields").innerHTML = completionFields(visit);
    readCompletionDraft();
    updateReviewValidation();
  } else if (!leaveAt && $("#completionForm")) {
    $("#completionFields").innerHTML = "";
  }
  saveActiveVisit();
  return true;
}

async function completeVisit(event) {
  event.preventDefault();
  const savingUser = state.user?.sub;
  if (!savingUser || !state.activeVisit) return;
  const button = event.target.querySelector('button[type="submit"]');
  if (button.disabled) return;
  if (!synchronizeManualTimes(true)) {
    $("#manualTimeError").scrollIntoView({ block: "center" });
    return;
  }
  button.disabled = true;
  readCompletionDraft();
  state.activeVisit.note = state.activeVisit.note.trim();
  state.activeVisit.stayMinutes = stayMinutes(state.activeVisit);
  state.activeVisit.userConfirmed = true;
  state.activeVisit.completedAt = new Date().toISOString();
  let savedVisit;
  try {
    const data = await authorizedFetch("/api/visits", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.activeVisit),
    });
    savedVisit = data.visit;
  } catch (error) {
    if (state.user?.sub !== savingUser) return;
    $("#accountStatus").textContent = error.message;
    button.disabled = false;
    saveActiveVisit();
    return;
  }
  if (state.user?.sub !== savingUser) return;
  state.visits = state.visits.filter((visit) => visit.id !== savedVisit.id);
  state.visits.push(savedVisit);
  state.reviewFeeds.clear();
  localStorage.removeItem(activeVisitStorageKey());
  state.activeVisit = null;
  selectLatestVisit();
  renderActiveVisit();
  renderCalendar();
  navigate("log");
}

function stayMinutes(visit) {
  if (!visit.arrivalAt || !visit.leaveAt) return 0;
  return Math.max(
    1,
    Math.round((new Date(visit.leaveAt) - new Date(visit.arrivalAt)) / 60000),
  );
}

function formatTime(value) {
  return new Date(value).toLocaleTimeString("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toDatetimeLocal(value) {
  if (!value) return "";
  const date = new Date(value);
  const pad = (number) => String(number).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatDate(value) {
  return new Date(value).toLocaleDateString("ja-JP", {
    month: "numeric",
    day: "numeric",
  });
}

function navigate(screen) {
  setAccountMenu(false);
  if (!state.user || !state.profile) {
    updateAccessScreen();
    return;
  }
  $(".tabbar").hidden = screen === "settings";
  document
    .querySelectorAll(".screen")
    .forEach((item) => item.classList.remove("active"));
  const tabScreen =
    screen === "results" || screen === "detail" ? "search" : screen;
  document
    .querySelectorAll(".tab")
    .forEach((item) =>
      item.classList.toggle("active", item.dataset.nav === tabScreen),
    );
  $(`#screen-${screen}`).classList.add("active");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderCalendar() {
  const year = state.calendarDate.getFullYear();
  const month = state.calendarDate.getMonth();
  const first = new Date(year, month, 1);
  const days = new Date(year, month + 1, 0).getDate();
  const monthVisits = state.visits.filter((visit) => {
    const date = new Date(visit.arrivalAt || visit.plannedAt);
    return date.getFullYear() === year && date.getMonth() === month;
  });
  const visitsByDate = monthVisits.reduce((acc, visit) => {
    const key = dateKey(new Date(visit.arrivalAt || visit.plannedAt));
    acc[key] = acc[key] || [];
    acc[key].push(visit);
    return acc;
  }, {});

  const selectedParts = state.selectedDate.split("-").map(Number);
  if (selectedParts[0] !== year || selectedParts[1] !== month + 1) {
    const latestVisit = [...monthVisits].sort(
      (a, b) =>
        new Date(b.arrivalAt || b.plannedAt) -
        new Date(a.arrivalAt || a.plannedAt),
    )[0];
    state.selectedDate = latestVisit
      ? dateKey(new Date(latestVisit.arrivalAt || latestVisit.plannedAt))
      : `${year}-${String(month + 1).padStart(2, "0")}-01`;
  }

  $("#recordMonth").value = `${year}-${String(month + 1).padStart(2, "0")}`;
  const names = ["月", "火", "水", "木", "金", "土", "日"];
  const blanks = (first.getDay() + 6) % 7;
  const cells = names.map((name) => `<div class="day-name">${name}</div>`);

  for (let i = 0; i < blanks; i += 1) {
    cells.push(
      '<button class="day-cell empty" type="button" tabindex="-1"></button>',
    );
  }

  for (let day = 1; day <= days; day += 1) {
    const key = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const hasVisit = Boolean(visitsByDate[key]);
    cells.push(`
      <button class="day-cell ${hasVisit ? "has-visit" : ""} ${state.selectedDate === key ? "selected" : ""}" type="button" data-date="${key}">
        <span class="day-number">${day}</span>
        ${hasVisit ? '<span class="dot"></span>' : ""}
      </button>
    `);
  }

  $("#calendar").innerHTML = cells.join("");
  renderMonthlySummary(monthVisits);
  renderMonthDetails(monthVisits, year, month);
  renderDayDetails(visitsByDate[state.selectedDate] || []);
  renderRecordView();
}

function renderMonthlySummary(monthVisits) {
  const totalMinutes = monthVisits.reduce(
    (sum, visit) => sum + (visit.stayMinutes || stayMinutes(visit)),
    0,
  );
  const avg = monthVisits.length
    ? Math.round(totalMinutes / monthVisits.length)
    : 0;
  $("#monthlySummary").innerHTML = `
    <div class="summary-item"><span>受診回数</span><strong>${monthVisits.length}<small>回</small></strong></div>
    <div class="summary-item"><span>滞在時間</span><strong>${totalMinutes}<small>分</small></strong></div>
    <div class="summary-item"><span>平均</span><strong>${avg}<small>分</small></strong></div>
  `;
}

function renderRecordView() {
  const isMonthView = state.recordView === "month";
  $("#monthRecordView").hidden = !isMonthView;
  $("#dayRecordView").hidden = isMonthView;
  document.querySelectorAll("[data-record-view]").forEach((button) => {
    const isActive = button.dataset.recordView === state.recordView;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  });
}

function visitRecordMarkup(visit) {
  const post = {
    ...visit,
    visitedMonth: reviewMonth(visit.arrivalAt || visit.plannedAt),
    stayMinutes: visit.stayMinutes || stayMinutes(visit),
  };
  return `
    <article class="personal-record community-card review-own">
      <div class="record-hospital">
        <h4>${escapeHtml(visit.hospitalName)}</h4>
        <span class="department-label">${escapeHtml(departments[visit.department] || "診療科未設定")}</span>
      </div>
      ${reviewContentMarkup(post, { showAuthor: false })}
    </article>
  `;
}

function renderMonthDetails(visits, year, month) {
  $("#monthRecordsTitle").textContent = `${year}年${month + 1}月に受診した病院`;
  if (!visits.length) {
    $("#monthDetails").innerHTML = `
      <div class="empty-record">
        <strong>この月の記録はありません</strong>
        <span>ほかの月を選ぶと、その月に受診した病院を確認できます。</span>
      </div>
    `;
    return;
  }

  $("#monthDetails").innerHTML = [...visits]
    .sort(
      (a, b) =>
        new Date(b.arrivalAt || b.plannedAt) -
        new Date(a.arrivalAt || a.plannedAt),
    )
    .map((visit) => visitRecordMarkup(visit))
    .join("");
}

function renderDayDetails(visits) {
  const [, month, day] = state.selectedDate.split("-").map(Number);
  $("#selectedDateTitle").textContent = `${month}月${day}日の受診記録`;
  if (!visits.length) {
    $("#dayDetails").innerHTML = `
      <div class="empty-record">
        <strong>この日の記録はありません</strong>
        <span>記録がある日にはカレンダーに青い印が付きます。</span>
      </div>
    `;
    return;
  }
  $("#dayDetails").innerHTML = visits
    .map((visit) => visitRecordMarkup(visit))
    .join("");
}

function getHospitalReviews(hospital) {
  const records = state.visits
    .filter(
      (visit) =>
        visit.hospitalId === hospital.id &&
        visit.id !== "demo" &&
        !visit.reviewSharing?.published,
    )
    .sort(
      (a, b) =>
        new Date(b.arrivalAt || b.plannedAt) -
        new Date(a.arrivalAt || a.plannedAt),
    )
    .map((visit) => ({
      ...visit,
      id: `visit:${visit.id}`,
      visitedAt: `${formatDate(visit.arrivalAt || visit.plannedAt)} ${formatTime(visit.arrivalAt || visit.plannedAt)}`,
      stayMinutes: visit.stayMinutes || stayMinutes(visit),
      feeAmount:
        visit.feeAmount === "" || visit.feeAmount == null
          ? null
          : Number(visit.feeAmount),
      isOwnRecord: true,
      privateRecord: true,
      gradeLabel: profileGradeLabel(),
      visitedMonth: reviewMonth(visit.arrivalAt || visit.plannedAt),
    }));

  return [...(state.reviewFeeds.get(hospital.id)?.posts || []), ...records];
}

function reviewMonth(value) {
  if (!value) return "";
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Tokyo",
      year: "numeric",
      month: "2-digit",
    })
      .formatToParts(new Date(value))
      .map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}`;
}

function reviewTextMarkup(post, includePoints = true) {
  return `
    ${includePoints && post.positivePoints?.length ? `<ul class="review-point-list" aria-label="よかった点">${post.positivePoints.map((point) => `<li>${escapeHtml(point)}</li>`).join("")}</ul>` : ""}
    ${post.sceneText ? `<div class="review-narrative"><h5>よかった点の具体的なエピソード</h5><p class="review-note">${escapeHtml(post.sceneText)}</p></div>` : ""}
    ${post.adviceText ? `<div class="review-narrative"><h5>次に行く学生へ</h5><p class="review-note">${escapeHtml(post.adviceText)}</p></div>` : ""}
    ${post.note ? `<p class="review-note">${escapeHtml(post.note)}</p>` : ""}
  `;
}

function reviewVerificationBadge(post) {
  if (post.universityEmailVerified !== true) return "";
  const university = new Map([
    ["miyazaki", "宮崎大学"],
    ["doshisha", "同志社大学"],
  ]).get(post.verifiedEmailUniversity ?? "miyazaki");
  if (!university) return "";
  const label = `${university}メール認証済み`;
  const description = `${label}。大学メールの確認を示し、大学による公式認定ではありません。`;
  return `<span class="review-verified review-university-badge" role="img" aria-label="${label}" title="${description}"><img src="assets/universities/miyazaki-symbol.png" alt="" width="24" height="24" /><span class="review-verification-label" aria-hidden="true">認証済み</span></span>`;
}

function reviewContentMarkup(post, { showAuthor = true } = {}) {
  const month = /^\d{4}-(0[1-9]|1[0-2])$/.test(post.visitedMonth || "")
    ? `${post.visitedMonth.slice(0, 4)}年${Number(post.visitedMonth.slice(5))}月`
    : "";
  const nickname = String(
    post.nickname || (post.privateRecord ? "自分の記録" : "宮大生"),
  );
  const conditions = [post.visitType, post.reservationStatus].filter(
    (value) => value && value !== "未入力",
  );
  const metrics = [
    post.waitingMinutes != null
      ? `<div><dt>待ち時間</dt><dd>${Number(post.waitingMinutes)}<small>分</small></dd></div>`
      : "",
    post.stayMinutes != null
      ? `<div><dt>院内滞在</dt><dd>${Number(post.stayMinutes)}<small>分</small></dd></div>`
      : "",
    post.feeAmount != null && post.feeAmount !== ""
      ? `<div><dt>費用</dt><dd>${formatCurrency(Number(post.feeAmount))}</dd></div>`
      : "",
  ].filter(Boolean);
  const points = post.positivePoints || [];
  const text = reviewTextMarkup(post, false);
  const visitTimes = reviewVisitTimesMarkup(post);
  const verificationBadge = reviewVerificationBadge(post);
  const monthMarkup =
    month && !visitTimes
      ? `<div class="review-month"><time datetime="${escapeHtml(post.visitedMonth)}" aria-label="受診した月">${month}</time></div>`
      : "";
  return `
    ${
      showAuthor
        ? `<header class="community-card-header">
      <span class="review-avatar ${post.isOwnRecord ? "review-avatar-own" : ""}" aria-hidden="true">${escapeHtml(Array.from(nickname)[0])}</span>
      <div class="review-author">
        <strong>${escapeHtml(nickname)}</strong>
        ${post.gradeLabel || post.gradeBand ? `<span>${escapeHtml(post.gradeLabel || post.gradeBand)}</span>` : ""}
      </div>
      ${verificationBadge || monthMarkup ? `<div class="review-header-meta">${verificationBadge}${monthMarkup}</div>` : ""}
    </header>`
        : monthMarkup
    }
    ${visitTimes}
    ${conditions.length || points.length ? `<ul class="review-point-list review-tags" aria-label="受診条件とよかった点">${conditions.map((value) => `<li class="review-condition">${escapeHtml(value)}</li>`).join("")}${points.map((point) => `<li>${escapeHtml(point)}</li>`).join("")}</ul>` : ""}
    ${text.trim() ? `<div class="review-body">${text}</div>` : ""}
    ${metrics.length ? `<dl class="review-metrics">${metrics.join("")}</dl>` : ""}
  `;
}

function reviewVisitTimesMarkup(post) {
  if (!post.arrivalAt || !post.leaveAt) return "";
  const arrival = new Date(post.arrivalAt);
  const leave = new Date(post.leaveAt);
  if (
    !Number.isFinite(arrival.getTime()) ||
    !Number.isFinite(leave.getTime()) ||
    leave < arrival
  )
    return "";
  const dateFormat = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
  const timeFormat = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const arrivalDate = dateFormat.format(arrival);
  const leaveDate = dateFormat.format(leave);
  return `<div class="review-visit-times"><span>受診日時</span><div><time datetime="${escapeHtml(post.arrivalAt)}">${arrivalDate} ${timeFormat.format(arrival)}</time><span>〜</span><time datetime="${escapeHtml(post.leaveAt)}">${arrivalDate === leaveDate ? "" : `${leaveDate} `}${timeFormat.format(leave)}</time></div></div>`;
}

function renderReviewCards(hospital) {
  const posts = getHospitalReviews(hospital);
  const feed = state.reviewFeeds.get(hospital.id);
  const status = feed?.loading
    ? '<p class="muted" role="status">口コミを読み込み中</p>'
    : feed?.error
      ? `<p class="form-error" role="status">${escapeHtml(feed.error)}</p><button class="secondary-button" type="button" data-retry-reviews>再読み込み</button>`
      : "";
  return (
    status +
    (posts.length
      ? posts
          .map(
            (post) => `
    <article class="community-card ${post.privateRecord ? "review-private" : post.isOwnRecord ? "review-own" : ""}">
      ${reviewContentMarkup(post)}
    </article>
  `,
          )
          .join("")
      : feed?.loading || feed?.error
        ? ""
        : '<div class="empty-record"><strong>この病院の口コミはまだありません</strong></div>')
  );
}

async function loadHospitalReviews(hospital) {
  const subject = state.user?.sub;
  state.reviewFeeds.set(hospital.id, { posts: [], loading: true });
  try {
    const data = await authorizedFetch(
      `/api/reviews?${new URLSearchParams({ hospitalId: hospital.id })}`,
    );
    if (state.user?.sub !== subject) return;
    state.reviewFeeds.set(hospital.id, { posts: data.reviews });
  } catch (error) {
    if (state.user?.sub !== subject) return;
    state.reviewFeeds.set(hospital.id, { posts: [], error: error.message });
  }
  if (state.selectedHospital?.id === hospital.id && $("#hospitalReviews")) {
    $("#hospitalReviews").innerHTML = renderReviewCards(hospital);
    $("#reviewCount").textContent = `${getHospitalReviews(hospital).length}件`;
  }
}

function activeVisitStorageKey() {
  return `campusClinicActiveVisit:${state.user.sub}`;
}

function loadActiveVisit() {
  if (!state.user) return;
  try {
    state.activeVisit = JSON.parse(
      localStorage.getItem(activeVisitStorageKey()) || "null",
    );
  } catch {
    state.activeVisit = null;
  }
}

function saveActiveVisit() {
  if (state.user)
    localStorage.setItem(
      activeVisitStorageKey(),
      JSON.stringify(state.activeVisit),
    );
}

function bindEvents() {
  $("#settingsButton").addEventListener("click", openAccountSettings);
  $("#settingsBackButton").addEventListener("click", () =>
    navigate(state.settingsReturnScreen),
  );
  $("#settingsForm").addEventListener("submit", saveAccountSettings);
  $("#settingsNickname").addEventListener("input", () =>
    $("#settingsNickname").setCustomValidity(""),
  );
  $("#withdrawButton").addEventListener("click", () => {
    if (!state.user || state.savingSettings || state.deletingAccount) return;
    $("#deleteAccountForm").reset();
    $("#deleteAccountStatus").textContent = "";
    $("#confirmDeleteAccount").disabled = true;
    $("#deleteAccountDialog").showModal();
  });
  $("#cancelDeleteAccount").addEventListener("click", () =>
    $("#deleteAccountDialog").close(),
  );
  $("#deleteAccountDialog").addEventListener("cancel", (event) => {
    if (state.deletingAccount) event.preventDefault();
  });
  $("#deleteAccountConfirmed").addEventListener("change", (event) => {
    $("#confirmDeleteAccount").disabled =
      !event.target.checked || state.deletingAccount;
  });
  $("#accountButton").addEventListener("click", () =>
    setAccountMenu($("#accountMenu").hidden),
  );
  $("#accountButton").addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setAccountMenu(true);
      $("#settingsButton").focus();
    }
  });
  $("#accountControl").addEventListener("focusout", (event) => {
    if (!event.currentTarget.contains(event.relatedTarget))
      setAccountMenu(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#accountMenu").hidden) {
      event.preventDefault();
      setAccountMenu(false, true);
    }
  });
  $("#accountAvatar").addEventListener("load", () => {
    if (!state.user || !$("#accountAvatar").getAttribute("src")) return;
    $("#accountAvatar").hidden = false;
    $("#accountInitial").hidden = true;
  });
  $("#accountAvatar").addEventListener("error", () => {
    $("#accountAvatar").hidden = true;
    $("#accountInitial").hidden = false;
  });
  $("#signupButton").addEventListener("click", async () => {
    if (!state.authClient || state.loggingOut) return;
    try {
      await state.authClient.loginWithRedirect({
        authorizationParams: {
          screen_hint: "signup",
          ...(explicitlySignedOut() ? { prompt: "login" } : {}),
        },
      });
    } catch (error) {
      $("#accountStatus").textContent = error.message;
    }
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest("#accountControl")) setAccountMenu(false);
  });
  $("#profileForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const button = form.querySelector('button[type="submit"]');
    const status = $("#profileStatus");
    const subject = state.user?.sub;
    if (button.disabled || !subject) return;
    $("#profileNickname").setCustomValidity(
      $("#profileNickname").value.trim()
        ? ""
        : "ニックネームを入力してください。",
    );
    $("#profileGrade").setCustomValidity(
      $("#profileGrade").value ? "" : "学年を選択してください。",
    );
    $("#profileGender").setCustomValidity(
      $("#profileGender").value
        ? ""
        : "性別または「回答しない」を選択してください。",
    );
    const invalidInput = form.querySelector(":invalid");
    if (invalidInput) {
      status.textContent = invalidInput.validationMessage;
      invalidInput.focus();
      return;
    }
    status.textContent = "";
    $("#accountStatus").textContent = "";
    button.disabled = true;
    button.textContent = "登録中…";
    form.setAttribute("aria-busy", "true");
    try {
      const data = await authorizedFetch("/api/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          grade: $("#profileGrade").value,
          gender: $("#profileGender").value,
          nickname: $("#profileNickname").value.trim(),
        }),
      });
      if (state.user?.sub !== subject) return;
      if (!data.profile?.nickname?.trim()) {
        throw new Error(
          "ニックネームを保存できませんでした。サーバーを再起動してから、もう一度登録してください。",
        );
      }
      state.profile = data.profile;
      await enterApplication();
      navigate("search");
    } catch (error) {
      status.textContent = error.message;
      if ($("#profileScreen").hidden)
        $("#accountStatus").textContent = error.message;
    } finally {
      button.disabled = false;
      button.textContent = "登録して始める";
      form.removeAttribute("aria-busy");
    }
  });
  $("#loginButton").addEventListener("click", async () => {
    if (!state.authClient || state.loggingOut) return;
    try {
      await state.authClient.loginWithRedirect(
        explicitlySignedOut()
          ? { authorizationParams: { prompt: "login" } }
          : undefined,
      );
    } catch (error) {
      $("#accountStatus").textContent = error.message;
    }
  });
  const logout = async () => {
    if (state.loggingOut) return;
    state.loggingOut = true;
    if (state.profile) navigate("search");
    rememberSignedOut(true);
    const client = state.authClient;
    state.user = null;
    state.emailVerification = null;
    state.emailVerificationCheckedAt = 0;
    state.profile = null;
    state.universityLocation = null;
    state.visits = [];
    state.reviewFeeds.clear();
    state.activeVisit = null;
    state.selectedHospital = null;
    state.savingSettings = false;
    state.deletingAccount = false;
    $("#deleteAccountDialog").close();
    $("#accountStatus").textContent = "";
    updateAccessScreen();
    $("#loginButton").disabled = true;
    $("#signupButton").disabled = true;
    try {
      if (client)
        await client.logout({
          logoutParams: { returnTo: `${location.origin}/` },
        });
    } catch {
      $("#accountStatus").textContent =
        "アプリからログアウトしました。Auth0との通信を完了できなかったため、次回ログイン時は認証し直してください。";
    } finally {
      state.loggingOut = false;
      $("#loginButton").disabled = !client;
      $("#signupButton").disabled = !client;
      hospitals = [];
      state.routeTimes.clear();
      state.routeCache.clear();
      if (state.resultMap) state.resultMap.remove();
      state.resultMap = null;
      state.resultMapBounds = null;
      document
        .querySelectorAll(
          "#detail, #results, #activeVisit, #monthDetails, #dayDetails, #monthlySummary, #calendar",
        )
        .forEach((element) => element.replaceChildren());
      $("#profileForm").reset();
      $("#settingsForm").reset();
      $("#settingsForm").removeAttribute("aria-busy");
      $("#settingsFields").disabled = false;
      $("#settingsSaveButton").disabled = false;
      $("#settingsSaveButton").textContent = "変更を保存";
      $("#settingsStatus").textContent = "";
      $("#withdrawButton").disabled = false;
    }
  };
  $("#deleteAccountForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const subject = state.user?.sub;
    if (
      !subject ||
      state.savingSettings ||
      state.deletingAccount ||
      !$("#deleteAccountConfirmed").checked
    )
      return;
    state.deletingAccount = true;
    $("#deleteAccountStatus").textContent = "";
    $("#confirmDeleteAccount").disabled = true;
    $("#cancelDeleteAccount").disabled = true;
    $("#deleteAccountConfirmed").disabled = true;
    $("#confirmDeleteAccount").textContent = "削除中...";
    event.target.setAttribute("aria-busy", "true");
    try {
      const data = await authorizedFetch("/api/account", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation: "delete-account" }),
      });
      if (state.user?.sub !== subject) return;
      if (data.deleted !== true)
        throw new Error("退会を完了できませんでした。もう一度お試しください。");
      try {
        localStorage.removeItem(activeVisitStorageKey());
      } catch {
        // Server-side deletion is complete even when browser storage is unavailable.
      }
      await logout();
      $("#accountStatus").textContent =
        "退会しました。アプリ内のデータを削除しました。";
    } catch (error) {
      if (state.user?.sub !== subject) return;
      $("#deleteAccountStatus").textContent = error.message;
    } finally {
      state.deletingAccount = false;
      $("#confirmDeleteAccount").disabled = !$("#deleteAccountConfirmed")
        .checked;
      $("#cancelDeleteAccount").disabled = false;
      $("#deleteAccountConfirmed").disabled = false;
      $("#confirmDeleteAccount").textContent = "削除して退会";
      $("#deleteAccountForm").removeAttribute("aria-busy");
    }
  });
  $("#logoutButton").addEventListener("click", logout);
  $("#profileLogoutButton").addEventListener("click", logout);
  $("#searchForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.user || !state.profile) return;
    if (!(await ensureSearchOrigin())) return;
    navigate("results");
    try {
      await renderResults();
    } catch (error) {
      $("#accountStatus").textContent = error.message;
    }
  });

  document.body.addEventListener("click", (event) => {
    const detailButton = event.target.closest("[data-detail]");
    const planButton = event.target.closest("[data-plan]");
    const navButton = event.target.closest("[data-nav]");
    const dateButton = event.target.closest("[data-date]");
    const recordViewButton = event.target.closest("[data-record-view]");

    if (event.target.closest("[data-retry-reviews]") && state.selectedHospital)
      renderDetail(state.selectedHospital.id);
    if (detailButton) renderDetail(detailButton.dataset.detail);
    if (planButton) planVisit(planButton.dataset.plan);
    if (navButton) navigate(navButton.dataset.nav);
    if (recordViewButton) {
      state.recordView = recordViewButton.dataset.recordView;
      renderRecordView();
    }
    if (dateButton) {
      state.selectedDate = dateButton.dataset.date;
      renderCalendar();
    }
  });

  document.body.addEventListener("submit", (event) => {
    if (event.target.id === "completionForm") completeVisit(event);
  });

  document.body.addEventListener("input", (event) => {
    if (!state.activeVisit) return;
    if (event.target.closest("#manualTimeForm")) {
      synchronizeManualTimes();
      return;
    }
    if (!event.target.closest("#completionForm")) return;
    if (event.target.matches("[data-positive-point]") && event.target.checked) {
      const isNone = event.target.value === "特になし・分からない";
      document.querySelectorAll("[data-positive-point]").forEach((input) => {
        if (
          input !== event.target &&
          (isNone || input.value === "特になし・分からない")
        )
          input.checked = false;
      });
    }
    readCompletionDraft();
    updateReviewValidation();
    saveActiveVisit();
  });

  document.body.addEventListener("click", (event) => {
    if (event.target.id === "arrivalButton") markArrival();
    if (event.target.id === "leaveButton") markLeave();
  });

  document.querySelectorAll(".seg").forEach((button) => {
    button.addEventListener("click", () => {
      state.view = button.dataset.view;
      document
        .querySelectorAll(".seg")
        .forEach((item) => item.classList.toggle("active", item === button));
      $("#results").hidden = state.view !== "list";
      $("#mapView").hidden = state.view !== "map";
      if (state.view === "map") refreshResultMapSize();
    });
  });

  $("#prevMonth").addEventListener("click", () => {
    state.calendarDate = new Date(
      state.calendarDate.getFullYear(),
      state.calendarDate.getMonth() - 1,
      1,
    );
    renderCalendar();
  });

  $("#nextMonth").addEventListener("click", () => {
    state.calendarDate = new Date(
      state.calendarDate.getFullYear(),
      state.calendarDate.getMonth() + 1,
      1,
    );
    renderCalendar();
  });

  $("#recordMonth").addEventListener("change", (event) => {
    const [year, month] = event.target.value.split("-").map(Number);
    if (!year || !month) return;
    state.calendarDate = new Date(year, month - 1, 1);
    renderCalendar();
  });
}

function selectLatestVisit() {
  if (!state.visits.length) return;
  const latest = [...state.visits].sort((a, b) => {
    const aDate = new Date(a.arrivalAt || a.plannedAt);
    const bDate = new Date(b.arrivalAt || b.plannedAt);
    return bDate - aDate;
  })[0];
  const latestDate = new Date(latest.arrivalAt || latest.plannedAt);
  state.selectedDate = dateKey(latestDate);
  state.calendarDate = new Date(
    latestDate.getFullYear(),
    latestDate.getMonth(),
    1,
  );
}

function init() {
  setDefaultSearchTimes();
  bindEvents();
  renderActiveVisit();
  renderCalendar();
  initializeAuth();
}

init();
