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

const demoHospitals = [
  {
    id: "aoba",
    name: "青葉クリニック",
    address: "大学正門から東へ徒歩8分",
    departments: ["internal", "dermatology"],
    open: "09:00-17:30",
    baseTravel: 8,
    medianWait: 35,
    p60: 81,
    p90: 94,
    samples: 28,
    feeLow: 1500,
    feeHigh: 2500,
    phone: "075-000-1200",
    website: "https://example.com/aoba",
    maps: "https://www.google.com/maps/search/?api=1&query=Aoba+Clinic",
    x: 34,
    y: 40,
  },
  {
    id: "karasuma",
    name: "烏丸駅前メディカル",
    address: "地下鉄駅からすぐ",
    departments: ["internal", "eye", "ent"],
    open: "10:00-19:00",
    baseTravel: 14,
    medianWait: 22,
    p60: 90,
    p90: 98,
    samples: 46,
    feeLow: 1200,
    feeHigh: 3200,
    phone: "075-000-2220",
    website: "https://example.com/karasuma",
    maps: "https://www.google.com/maps/search/?api=1&query=Karasuma+Clinic",
    x: 62,
    y: 30,
  },
  {
    id: "kamogawa",
    name: "鴨川皮ふ科",
    address: "河原町通沿い",
    departments: ["dermatology"],
    open: "09:30-18:00",
    baseTravel: 18,
    medianWait: 48,
    p60: 62,
    p90: 88,
    samples: 17,
    feeLow: 1800,
    feeHigh: 3800,
    phone: "075-000-3030",
    website: "https://example.com/kamogawa",
    maps: "https://www.google.com/maps/search/?api=1&query=Kamogawa+Dermatology",
    x: 72,
    y: 56,
  },
  {
    id: "midorigaoka",
    name: "みどりヶ丘眼科",
    address: "大学西門から徒歩11分",
    departments: ["eye"],
    open: "08:45-16:30",
    baseTravel: 11,
    medianWait: 29,
    p60: 86,
    p90: 96,
    samples: 33,
    feeLow: 900,
    feeHigh: 2400,
    phone: "075-000-4141",
    website: "https://example.com/midorigaoka",
    maps: "https://www.google.com/maps/search/?api=1&query=Midorigaoka+Eye+Clinic",
    x: 22,
    y: 62,
  },
  {
    id: "sakura",
    name: "さくらウィメンズクリニック",
    address: "キャンパス南口から徒歩16分",
    departments: ["gynecology"],
    open: "09:00-18:30",
    baseTravel: 16,
    medianWait: 42,
    p60: 74,
    p90: 91,
    samples: 21,
    feeLow: 2200,
    feeHigh: 5200,
    phone: "075-000-5151",
    website: "https://example.com/sakura",
    maps: "https://www.google.com/maps/search/?api=1&query=Sakura+Womens+Clinic",
    x: 48,
    y: 72,
  },
];

const bundledFacilities = Array.isArray(window.FACILITY_DATA) && window.FACILITY_DATA.length
  ? window.FACILITY_DATA
  : demoHospitals;
let hospitals = bundledFacilities;

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
  user: null,
  profile: null,
  universities: [],
  reviewFeeds: new Map(),
  universityLocation: null,
  universityOptionIndex: -1,
  currentLocation: null,
  routeTimes: new Map(),
  routeCache: new Map(),
  resultMap: null,
  resultMapBounds: null,
};

const $ = (selector) => document.querySelector(selector);

function updateAccessScreen() {
  const canEnter = Boolean(state.authReady && state.user && state.profile);
  $("#appContent").hidden = !canEnter;
  $("#loginScreen").hidden = !state.authReady || Boolean(state.user);
  $("#profileScreen").hidden = !state.authReady || !state.user || canEnter;
  $("#logoutButton").hidden = !state.user;
  if (canEnter) {
    $("#profileSummary").textContent = `${state.profile.universityName} / ${state.user.name || "ログイン中"}`;
    $('#originType option[value="university"]').textContent = `自分の大学（${state.profile.universityName}）`;
  }
}

function renderUniversityOptions() {
  const query = $("#universitySearch").value.normalize("NFKC").toLowerCase().trim();
  const options = state.universities.filter((university) =>
    `${university.name} ${university.prefecture}`.normalize("NFKC").toLowerCase().includes(query)).slice(0, 20);
  const suggestions = $("#universitySuggestions");
  suggestions.replaceChildren();
  state.universityOptionIndex = -1;
  $("#universitySearch").removeAttribute("aria-activedescendant");
  suggestions.hidden = !query;
  $("#universitySearch").setAttribute("aria-expanded", String(Boolean(query)));
  if (!query) return;
  options.forEach((university, index) => {
    const button = document.createElement("button");
    button.id = `university-option-${index}`;
    button.type = "button";
    button.tabIndex = -1;
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", "false");
    button.textContent = `${university.name}（${university.prefecture}）`;
    button.addEventListener("mousedown", (event) => event.preventDefault());
    button.addEventListener("click", () => {
      $("#universitySelect").value = university.id;
      $("#universitySearch").value = university.name;
      $("#universitySearch").setCustomValidity("");
      $("#universitySelection").textContent = `${university.name} / ${university.prefecture}`;
      closeUniversityOptions();
    });
    suggestions.appendChild(button);
  });
  if (!options.length) {
    const message = document.createElement("span");
    message.textContent = "候補がありません";
    suggestions.appendChild(message);
  }
}

function closeUniversityOptions() {
  $("#universitySuggestions").hidden = true;
  $("#universitySearch").setAttribute("aria-expanded", "false");
  $("#universitySearch").removeAttribute("aria-activedescendant");
}

async function openProfileRegistration() {
  updateAccessScreen();
  const data = await authorizedFetch("/api/universities");
  state.universities = data.universities;
  renderUniversityOptions();
  $("#accountStatus").textContent = "";
}

async function enterApplication() {
  const data = await authorizedFetch("/api/visits");
  state.visits = data.visits;
  loadActiveVisit();
  selectLatestVisit();
  renderActiveVisit();
  renderCalendar();
  updateStatus();
  updateAccessScreen();
  $("#accountStatus").textContent = "";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function authorizedFetch(path, options = {}) {
  if (!state.user || !state.authClient) throw new Error("ログインしてください。");
  const subject = state.user.sub;
  const request = async (refresh) => {
    const token = await state.authClient.getTokenSilently(refresh ? { cacheMode: "off" } : {});
    if (state.user?.sub !== subject) throw new Error("ログイン状態が変更されました。");
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
  if (!response.ok) {
    if (response.status === 401) {
      state.user = null;
      state.profile = null;
      state.visits = [];
      state.activeVisit = null;
      updateAccessScreen();
    } else if (data.code === "profile_required") {
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
    if (response.status === 404) throw new Error("認証APIがありません。python server.py で起動したURLを開いてください。");
    if (!response.ok) throw new Error("ログイン設定を読み込めませんでした。");
    const config = await response.json();
    if (!config.configured) {
      throw new Error("ログイン設定が未完了です。.env のAuth0設定を確認してサーバーを再起動してください。");
    }
    if (!window.auth0) throw new Error("ログイン機能を読み込めませんでした。");
    state.authClient = new auth0.Auth0Client({
      domain: config.domain,
      clientId: config.clientId,
      authorizationParams: { redirect_uri: `${location.origin}/`, audience: config.audience },
    });
    const parameters = new URLSearchParams(location.search);
    if (parameters.has("state") && (parameters.has("code") || parameters.has("error"))) {
      try {
        await state.authClient.handleRedirectCallback();
      } finally {
        const cleanUrl = new URL(location.href);
        ["code", "state", "error", "error_description", "iss", "session_state"].forEach((key) => cleanUrl.searchParams.delete(key));
        history.replaceState({}, document.title, `${cleanUrl.pathname}${cleanUrl.search}${cleanUrl.hash}`);
      }
    } else {
      try {
        await state.authClient.checkSession();
      } catch (error) {
        if (!["login_required", "consent_required", "interaction_required", "missing_refresh_token"].includes(error.error)) throw error;
      }
    }
    if (await state.authClient.isAuthenticated()) {
      state.user = await state.authClient.getUser();
      $("#accountStatus").textContent = state.user.name || state.user.email || "ログイン中";
      const data = await authorizedFetch("/api/profile");
      state.profile = data.profile;
      if (state.profile) await enterApplication();
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
  updateStatus();
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
  const normalized = ((totalMinutes % (24 * 60)) + (24 * 60)) % (24 * 60);
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

function feeRange(hospital) {
  if (!Number.isFinite(hospital.feeLow) || !Number.isFinite(hospital.feeHigh)) return "データなし";
  return `${formatCurrency(hospital.feeLow)}〜${formatCurrency(hospital.feeHigh)}`;
}

function calculateDistanceKm(origin, destination) {
  const toRadians = (value) => (value * Math.PI) / 180;
  const latitudeDelta = toRadians(destination.latitude - origin.latitude);
  const longitudeDelta = toRadians(destination.longitude - origin.longitude);
  const a = Math.sin(latitudeDelta / 2) ** 2
    + Math.cos(toRadians(origin.latitude)) * Math.cos(toRadians(destination.latitude))
    * Math.sin(longitudeDelta / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function getSelectedOrigin() {
  const originType = $("#originType").value;
  if (originType === "current") return state.currentLocation;
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
  const estimate = Math.max(3, Math.round(walkingMinutes * transportSpeed[transportation]));
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
  if (data.code !== "Ok") throw new Error(data.message || "OSRMから経路を取得できませんでした");
  return data;
}

async function loadOsrmRoutes(hospitalResults) {
  if (!hospitalResults.length) return 0;
  const origin = getSelectedOrigin();
  const transportation = $("#transportation").value;
  const server = osrmServers[transportation];
  const cachePrefix = `${transportation}:${origin.latitude.toFixed(5)},${origin.longitude.toFixed(5)}`;
  const cachedRoutes = hospitalResults.map(({ hospital }) => state.routeCache.get(`${cachePrefix}:${hospital.id}`));
  if (cachedRoutes.every(Boolean)) {
    hospitalResults.forEach(({ hospital }, index) => state.routeTimes.set(hospital.id, cachedRoutes[index]));
    return hospitalResults.length;
  }
  const coordinates = [origin, ...hospitalResults.map(({ hospital }) => hospital)]
    .map((point) => `${point.longitude},${point.latitude}`)
    .join(";");
  const destinationIndexes = hospitalResults.map((_, index) => index + 1).join(";");
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
  const startTime = $("#when").value === "now" ? timeFromDate(new Date()) : $("#startTime").value;
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

function getCurrentLocation() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("この端末では現在地を取得できません"));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => resolve({
        label: "現在地",
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
      }),
      () => reject(new Error("現在地を取得できませんでした。位置情報を許可してください")),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  });
}

function updateLocationStatus(message) {
  const status = $("#locationStatus");
  if (status) status.textContent = message;
}

async function ensureSearchOrigin() {
  const usesCurrentLocation = $("#originType").value === "current";
  if (getSelectedOrigin()) return true;
  const button = $(".search-submit");
  const previousLabel = button.textContent;
  button.disabled = true;
  button.textContent = usesCurrentLocation ? "現在地を取得しています" : "大学の所在地を取得しています";
  updateLocationStatus("位置情報を確認しています…");
  try {
    if (usesCurrentLocation) {
      state.currentLocation = await getCurrentLocation();
      updateLocationStatus("現在地を取得しました");
    } else {
      const data = await authorizedFetch("/api/university-origin");
      state.universityLocation = data.origin;
      updateLocationStatus(`${data.origin.label} / ${data.origin.matchedAddress || data.origin.address}`);
    }
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
    hospitals = Array.isArray(data.facilities) ? data.facilities : [];
    return true;
  } catch (error) {
    console.warn("Facility API lookup failed", error);
    if (error.status === 401 || error.status === 403) throw error;
    hospitals = bundledFacilities;
    return false;
  }
}

function evaluateHospital(hospital) {
  const context = getSearchContext();
  const travel = getTravelDurations(hospital);
  const total = travel.outbound + travel.inbound + hospital.medianWait;
  const returnAt = context.start + total;
  const remaining = context.returnBy - context.start - total;
  const fit = remaining >= 30 ? "good" : remaining >= 10 ? "warn" : remaining >= 0 ? "tight" : "bad";
  return { ...travel, total, returnAt, remaining, fit };
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
  if (estimate.remaining >= 30) return `予定まで${estimate.remaining}分の余裕があります`;
  if (estimate.remaining >= 0) return `予定まで残り${estimate.remaining}分です`;
  return `予定を約${Math.abs(estimate.remaining)}分超える見込みです`;
}

function matchingHospitals() {
  const { department } = getSearchContext();
  return hospitals
    .filter((hospital) => {
      if (getFacilityDistance(hospital) > 12) return false;
      return ["hospital", "clinic"].includes(hospital.type) && hospital.departments.includes(department);
    })
    .map((hospital) => ({ hospital, estimate: evaluateHospital(hospital) }))
    .sort((a, b) => b.estimate.remaining - a.estimate.remaining)
    .slice(0, 15);
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
    mapSurface.innerHTML = '<div class="map-error">地図を読み込めませんでした。インターネット接続を確認してください。</div>';
    return;
  }

  mapSurface.innerHTML = "";
  const origin = getSelectedOrigin();
  const map = L.map(mapSurface, { zoomControl: true });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  const points = [[origin.latitude, origin.longitude]];
  L.circleMarker([origin.latitude, origin.longitude], {
    radius: 8,
    color: "#ffffff",
    weight: 3,
    fillColor: "#1769e0",
    fillOpacity: 1,
  }).addTo(map).bindTooltip(origin.label, { direction: "top" });

  results.forEach(({ hospital, estimate }) => {
    const point = [hospital.latitude, hospital.longitude];
    points.push(point);
    L.marker(point)
      .addTo(map)
      .bindPopup(createMapPopup(hospital, estimate));
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
      state.resultMap.fitBounds(state.resultMapBounds, { padding: [28, 28], maxZoom: 15 });
    }
  }, 0);
}

async function renderResults() {
  state.routeTimes.clear();
  const context = getSearchContext();
  const startLabel = $("#when").value === "now" ? "今すぐ" : `${$("#startTime").value}出発`;
  const targetLabel = departments[context.department];
  const originLabel = getSelectedOrigin()?.label || "現在地";
  $("#searchSummary").textContent = `${originLabel}から / ${targetLabel} / ${startLabel} / ${$("#returnTime").value}まで / ${transportationLabels[$("#transportation").value]}`;
  $("#routeStatus").className = "route-status loading";
  $("#routeStatus").textContent = "全国施設DBから周辺の施設を探しています…";
  $("#results").innerHTML = '<div class="route-loading">周辺施設を検索しています</div>';
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
      ? "現在地から12km以内に条件に合う施設がありません"
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

  $("#routeStatus").className = "route-status loading";
  $("#routeStatus").textContent = "OSRMで往復経路を計算しています…";
  $("#results").innerHTML = '<div class="route-loading">経路時間を取得しています</div>';
  const osrmRouteCount = await loadOsrmRoutes(results);
  results = results
    .map(({ hospital }) => ({ hospital, estimate: evaluateHospital(hospital) }))
    .sort((a, b) => b.estimate.remaining - a.estimate.remaining);
  $("#routeStatus").className = `route-status ${osrmRouteCount === results.length ? "success" : "warning"}`;
  if (osrmRouteCount === results.length) {
    $("#routeStatus").textContent = "OpenStreetMapの道路データから往復時間を計算しました";
  } else if (osrmRouteCount > 0) {
    $("#routeStatus").textContent = `${osrmRouteCount}件はOSRM経路、残りは直線距離による概算です`;
  } else {
    $("#routeStatus").textContent = "OSRMに接続できないため、直線距離による概算を表示しています";
  }
  if (!loadedFromApi) {
    $("#routeStatus").className = "route-status warning";
    $("#routeStatus").textContent += " / 施設は同梱データを使用しています";
  }
  $("#results").innerHTML = results.map(({ hospital, estimate }) => `
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
        <div><span>${hospital.type === "pharmacy" ? "薬局滞在" : "院内滞在"}</span><strong>${hospital.medianWait}分</strong></div>
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
          <dd>${feeRange(hospital)}</dd>
        </div>
        <div>
          <dt>実測データ</dt>
          <dd>${hospital.samples ? `${hospital.samples}件` : "まだありません"}</dd>
        </div>
      </dl>

      <div class="card-actions">
        <button class="secondary-button" type="button" data-detail="${hospital.id}">詳しく見る</button>
        <button class="primary-button" type="button" data-plan="${hospital.id}">この施設に行く</button>
      </div>
    </article>
  `).join("");

  renderResultMap(results);
}

function renderDetail(hospitalId) {
  const hospital = hospitals.find((item) => item.id === hospitalId);
  const estimate = evaluateHospital(hospital);
  const departmentNames = hospital.departments.map((key) => departments[key] || key).join(" / ");
  const statsContent = hospital.samples && Number.isFinite(hospital.p60) && Number.isFinite(hospital.p90)
    ? `
      <div class="stats-list">
        ${progressRow("中央値", hospital.medianWait, 90)}
        ${progressRow("60分以内に終了", hospital.p60, 100, "%")}
        ${progressRow("90分以内に終了", hospital.p90, 100, "%")}
      </div>
    `
    : `
      <div class="stats-empty">
        <strong>実測データはまだありません</strong>
        <p>現在は施設種別から算出した${hospital.medianWait}分を仮の滞在目安として表示しています。</p>
      </div>
    `;
  state.selectedHospital = hospital;
  if (canShareReviews()) state.reviewFeeds.set(hospitalId, { posts: [], loading: true });
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
            <div class="metric"><span>施設区分</span><strong>${facilityTypeLabels[hospital.type] || "医療機関"}</strong></div>
            <div class="metric"><span>費用</span><strong>${feeRange(hospital)}</strong></div>
          </div>
          <div class="detail-actions">
            <button class="primary-button" type="button" data-plan="${hospital.id}">この施設に行く</button>
            <a class="secondary-button" href="${hospital.maps}" target="_blank" rel="noreferrer">Google Mapsで見る</a>
            ${hospital.website ? `<a class="secondary-button" href="${hospital.website}" target="_blank" rel="noreferrer">公式サイトを見る</a>` : ""}
          </div>
        </div>
        <aside>
          <h3>滞在時間データ</h3>
          ${statsContent}
          <p class="muted">${hospital.type === "pharmacy" ? "区分" : "診療科"}: ${departmentNames}</p>
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

function progressRow(label, value, max, suffix = "分") {
  const width = Math.min(100, Math.round((value / max) * 100));
  return `
    <div class="progress-row">
      <div class="progress-label"><span>${label}</span><strong>${value}${suffix}</strong></div>
      <div class="progress-bar"><span style="width:${width}%"></span></div>
    </div>
  `;
}

function planVisit(hospitalId) {
  if (!state.user) {
    $("#accountStatus").textContent = "受診記録を作成するにはログインしてください。";
    $("#loginButton").focus();
    return;
  }
  const hospital = hospitals.find((item) => item.id === hospitalId);
  const now = new Date();
  state.activeVisit = {
    id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
    hospitalId,
    hospitalName: hospital.name,
    department: hospital.type === "pharmacy" ? "pharmacy" : $("#department").value,
    status: "planned",
    plannedAt: now.toISOString(),
    arrivalAt: null,
    leaveAt: null,
    feeAmount: "",
    reservationStatus: "未入力",
    waitingImpression: "未入力",
    note: "",
    reviewSharing: { published: false, showGrade: true, showReservation: true, showDuration: true, showFee: true },
  };
  saveActiveVisit();
  navigate("active");
  renderActiveVisit();
  updateStatus();
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
        <p class="muted">${departments[visit.department]} / status = ${visit.status}</p>
      </div>
      <details class="manual-time-panel" open>
        <summary>到着・終了時刻を手入力</summary>
        <form class="manual-time-form" id="manualTimeForm">
          <label>病院への到着日時
            <input id="manualArrivalAt" type="datetime-local" value="${toDatetimeLocal(visit.arrivalAt)}" required />
          </label>
          <label>受診終了日時（任意）
            <input id="manualLeaveAt" type="datetime-local" value="${toDatetimeLocal(visit.leaveAt)}" />
          </label>
          <p class="form-error" id="manualTimeError" aria-live="polite"></p>
          <button class="secondary-button" type="submit">入力した時刻を反映</button>
        </form>
      </details>
      <div class="card-actions">
        <button class="primary-button" type="button" id="arrivalButton" ${visit.arrivalAt ? "disabled" : ""}>現在時刻で到着</button>
        <button class="secondary-button" type="button" id="leaveButton" ${!visit.arrivalAt || visit.leaveAt ? "disabled" : ""}>現在時刻で終了</button>
      </div>
      ${visit.leaveAt ? completionFields(visit) : ""}
    </div>
  `;
  if (visit.leaveAt) updateReviewPreview();
}

function completionFields(visit) {
  return `
    <form class="completion-form" id="completionForm">
      <label>費用（円）
        <input id="feeAmount" type="number" min="0" max="10000000" step="1" value="${escapeHtml(visit.feeAmount)}" placeholder="1840" />
      </label>
      <label>予約
        <select id="reservationStatus">
          <option ${visit.reservationStatus === "未入力" ? "selected" : ""}>未入力</option>
          <option ${visit.reservationStatus === "予約あり" ? "selected" : ""}>予約あり</option>
          <option ${visit.reservationStatus === "予約なし" ? "selected" : ""}>予約なし</option>
        </select>
      </label>
      <label>待ち時間
        <select id="waitingImpression">
          <option ${visit.waitingImpression === "未入力" ? "selected" : ""}>未入力</option>
          <option ${visit.waitingImpression === "スムーズ" ? "selected" : ""}>スムーズ</option>
          <option ${visit.waitingImpression === "普通" ? "selected" : ""}>普通</option>
          <option ${visit.waitingImpression === "待った" ? "selected" : ""}>待った</option>
        </select>
      </label>
      <label>口コミ（任意）
        <textarea id="visitNote" rows="4" maxlength="2000" placeholder="例：診察と薬で1,840円。待ち時間が短く、説明も丁寧だった。">${escapeHtml(visit.note || "")}</textarea>
      </label>
      ${canShareReviews() ? reviewSharingFields(visit) : ""}
      <button class="primary-button" type="submit">記録を保存</button>
    </form>
  `;
}

function canShareReviews() {
  return state.profile?.universityId === "F145110111523";
}

function profileGradeBand() {
  const grade = state.profile?.grade || "";
  if (["1", "2"].includes(grade)) return "学部1〜2年";
  if (["3", "4"].includes(grade)) return "学部3〜4年";
  if (["5", "6"].includes(grade)) return "学部5〜6年";
  return /^(master|doctor)/.test(grade) ? "大学院生" : "学生";
}

function reviewSharingFields(visit) {
  const sharing = { showGrade: true, showReservation: true, showDuration: true, showFee: true, ...visit.reviewSharing };
  return `
    <div class="review-publication">
      <label class="review-check"><input id="publishReview" type="checkbox" ${sharing.published ? "checked" : ""} />宮大生に口コミを公開する</label>
      <div id="reviewPublicationDetails" ${sharing.published ? "" : "hidden"}>
        <p class="review-privacy">公開先は宮崎大学を登録した利用者です。名前・性別・受診日時は公開しません。文章にも個人情報を含めないでください。</p>
        <fieldset class="review-options">
          <legend>一緒に公開する項目</legend>
          ${[["showGrade", "学年帯"], ["showReservation", "予約の有無"], ["showDuration", "滞在時間"], ["showFee", "費用"]].map(([key, label]) => `
            <label class="review-check"><input type="checkbox" data-review-field="${key}" ${sharing[key] ? "checked" : ""} />${label}</label>
          `).join("")}
        </fieldset>
        <div class="review-preview"><span class="field-label">公開内容の確認</span><div id="reviewPreview"></div></div>
      </div>
    </div>
  `;
}

function readCompletionDraft() {
  const visit = state.activeVisit;
  visit.feeAmount = $("#feeAmount").value;
  visit.reservationStatus = $("#reservationStatus").value;
  visit.waitingImpression = $("#waitingImpression").value;
  visit.note = $("#visitNote").value;
  visit.reviewSharing = { published: Boolean($("#publishReview")?.checked) };
  document.querySelectorAll("[data-review-field]").forEach((input) => {
    visit.reviewSharing[input.dataset.reviewField] = input.checked;
  });
}

function updateReviewPreview() {
  const preview = $("#reviewPreview");
  if (!preview) return;
  const visit = state.activeVisit;
  const sharing = visit.reviewSharing || {};
  $("#reviewPublicationDetails").hidden = !sharing.published;
  $("#visitNote").required = sharing.published;
  $('#completionForm button[type="submit"]').textContent = sharing.published ? "記録を保存して口コミを公開" : "記録を保存";
  const post = { note: visit.note, gradeBand: sharing.showGrade ? profileGradeBand() : null };
  if (sharing.showFee) post.feeAmount = visit.feeAmount;
  if (sharing.showDuration) post.stayMinutes = stayMinutes(visit);
  if (sharing.showReservation) post.reservationStatus = visit.reservationStatus;
  preview.innerHTML = reviewContentMarkup(post);
}

function markArrival() {
  state.activeVisit.arrivalAt = new Date().toISOString();
  state.activeVisit.arrivalMethod = "button";
  state.activeVisit.status = "measuring";
  saveActiveVisit();
  renderActiveVisit();
  updateStatus();
}

function markLeave() {
  state.activeVisit.leaveAt = new Date().toISOString();
  state.activeVisit.leaveMethod = "button";
  state.activeVisit.status = "completed";
  saveActiveVisit();
  renderActiveVisit();
  updateStatus();
}

function applyManualTimes(event) {
  event.preventDefault();
  if (!state.activeVisit) return;

  const arrivalValue = $("#manualArrivalAt").value;
  const leaveValue = $("#manualLeaveAt").value;
  const error = $("#manualTimeError");
  const arrivalAt = new Date(arrivalValue);
  const leaveAt = leaveValue ? new Date(leaveValue) : null;

  if (!arrivalValue || Number.isNaN(arrivalAt.getTime())) {
    error.textContent = "到着日時を入力してください。";
    return;
  }

  if (leaveAt && (Number.isNaN(leaveAt.getTime()) || leaveAt < arrivalAt)) {
    error.textContent = "終了日時は到着日時より後にしてください。";
    return;
  }

  state.activeVisit.arrivalAt = arrivalAt.toISOString();
  state.activeVisit.leaveAt = leaveAt ? leaveAt.toISOString() : null;
  state.activeVisit.arrivalMethod = "manual";
  state.activeVisit.leaveMethod = leaveAt ? "manual" : null;
  state.activeVisit.status = leaveAt ? "completed" : "measuring";
  saveActiveVisit();
  renderActiveVisit();
  updateStatus();
}

async function completeVisit(event) {
  event.preventDefault();
  const savingUser = state.user?.sub;
  if (!savingUser || !state.activeVisit) return;
  const button = event.target.querySelector('button[type="submit"]');
  if (button.disabled) return;
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
  updateStatus();
  navigate("log");
}

function stayMinutes(visit) {
  if (!visit.arrivalAt || !visit.leaveAt) return 0;
  return Math.max(1, Math.round((new Date(visit.leaveAt) - new Date(visit.arrivalAt)) / 60000));
}

function formatTime(value) {
  return new Date(value).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
}

function toDatetimeLocal(value) {
  if (!value) return "";
  const date = new Date(value);
  const pad = (number) => String(number).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatDate(value) {
  return new Date(value).toLocaleDateString("ja-JP", { month: "numeric", day: "numeric" });
}

function navigate(screen) {
  if (!state.user || !state.profile) {
    updateAccessScreen();
    return;
  }
  document.querySelectorAll(".screen").forEach((item) => item.classList.remove("active"));
  const tabScreen = screen === "results" || screen === "detail" ? "search" : screen;
  document.querySelectorAll(".tab").forEach((item) => item.classList.toggle("active", item.dataset.nav === tabScreen));
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
    const latestVisit = [...monthVisits].sort((a, b) => (
      new Date(b.arrivalAt || b.plannedAt) - new Date(a.arrivalAt || a.plannedAt)
    ))[0];
    state.selectedDate = latestVisit
      ? dateKey(new Date(latestVisit.arrivalAt || latestVisit.plannedAt))
      : `${year}-${String(month + 1).padStart(2, "0")}-01`;
  }

  $("#recordMonth").value = `${year}-${String(month + 1).padStart(2, "0")}`;
  const names = ["月", "火", "水", "木", "金", "土", "日"];
  const blanks = (first.getDay() + 6) % 7;
  const cells = names.map((name) => `<div class="day-name">${name}</div>`);

  for (let i = 0; i < blanks; i += 1) {
    cells.push('<button class="day-cell empty" type="button" tabindex="-1"></button>');
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
  const totalMinutes = monthVisits.reduce((sum, visit) => sum + (visit.stayMinutes || stayMinutes(visit)), 0);
  const avg = monthVisits.length ? Math.round(totalMinutes / monthVisits.length) : 0;
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

function visitRecordMarkup(visit, showDate = false) {
  const visitDate = new Date(visit.arrivalAt || visit.plannedAt);
  const duration = visit.stayMinutes || stayMinutes(visit);
  return `
    <article class="personal-record">
      <header>
        <div>
          ${showDate ? `<time class="record-date" datetime="${dateKey(visitDate)}">${formatDate(visitDate)}</time>` : ""}
          <span class="department-label">${departments[visit.department] || "診療科未設定"}</span>
          <h4>${escapeHtml(visit.hospitalName)}</h4>
        </div>
        <strong class="stay-time">${duration}<small>分</small></strong>
      </header>
      <dl>
        <div><dt>受診時間</dt><dd>${formatTime(visit.arrivalAt)}〜${formatTime(visit.leaveAt)}</dd></div>
        <div><dt>費用</dt><dd>${visit.feeAmount ? formatCurrency(Number(visit.feeAmount)) : "未入力"}</dd></div>
        <div><dt>予約</dt><dd>${visit.reservationStatus}</dd></div>
        <div><dt>待ち時間</dt><dd>${visit.waitingImpression}</dd></div>
      </dl>
      ${visit.note ? `<p class="review-note">${escapeHtml(visit.note)}</p>` : ""}
      <div class="record-sharing">
        <span>${visit.reviewSharing?.published ? "口コミを公開中" : "自分だけの記録"}</span>
        ${visit.reviewSharing?.published ? `<button class="secondary-button" type="button" data-unpublish="${escapeHtml(visit.id)}">口コミの公開を取り消す</button>` : ""}
      </div>
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
    .sort((a, b) => new Date(b.arrivalAt || b.plannedAt) - new Date(a.arrivalAt || a.plannedAt))
    .map((visit) => visitRecordMarkup(visit, true))
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
  $("#dayDetails").innerHTML = visits.map((visit) => visitRecordMarkup(visit)).join("");
}

function getHospitalReviews(hospital) {
  const records = state.visits
    .filter((visit) => visit.hospitalId === hospital.id && visit.id !== "demo" && !visit.reviewSharing?.published)
    .sort((a, b) => new Date(b.arrivalAt || b.plannedAt) - new Date(a.arrivalAt || a.plannedAt))
    .map((visit) => ({
      ...visit,
      id: `visit:${visit.id}`,
      visitedAt: `${formatDate(visit.arrivalAt || visit.plannedAt)} ${formatTime(visit.arrivalAt || visit.plannedAt)}`,
      stayMinutes: visit.stayMinutes || stayMinutes(visit),
      feeAmount: visit.feeAmount === "" || visit.feeAmount == null ? null : Number(visit.feeAmount),
      isOwnRecord: true,
      privateRecord: true,
      gradeBand: profileGradeBand(),
    }));

  return [...(state.reviewFeeds.get(hospital.id)?.posts || []), ...records];
}

function reviewContentMarkup(post) {
  return `
    <div class="review-author"><strong>${escapeHtml(post.gradeBand || "宮崎大学生")}</strong>${post.reservationStatus ? `<span>${escapeHtml(post.reservationStatus)}</span>` : ""}</div>
    <dl class="review-metrics">
      ${post.stayMinutes != null ? `<div><dt>滞在時間</dt><dd>${Number(post.stayMinutes)}<small>分</small></dd></div>` : ""}
      ${post.feeAmount != null ? `<div><dt>費用</dt><dd>${post.feeAmount === "" ? "未入力" : formatCurrency(Number(post.feeAmount))}</dd></div>` : ""}
    </dl>
    ${post.note ? `<p class="review-note">${escapeHtml(post.note)}</p>` : ""}
  `;
}

function renderReviewCards(hospital) {
  const posts = getHospitalReviews(hospital);
  const feed = state.reviewFeeds.get(hospital.id);
  const status = feed?.loading ? '<p class="muted" role="status">口コミを読み込み中</p>' : feed?.error ? `<p class="form-error" role="status">${escapeHtml(feed.error)}</p><button class="secondary-button" type="button" data-retry-reviews>再読み込み</button>` : "";
  return status + (posts.length ? posts.map((post) => `
    <article class="community-card">
      <span class="review-visibility">${post.privateRecord ? "自分の記録・非公開" : post.isOwnRecord ? "自分の口コミ・公開中" : "宮大生の口コミ"}</span>
      ${reviewContentMarkup(post)}
    </article>
  `).join("") : feed?.loading || feed?.error ? "" : '<div class="empty-record"><strong>この病院の口コミはまだありません</strong></div>');
}

async function loadHospitalReviews(hospital) {
  const subject = state.user?.sub;
  state.reviewFeeds.set(hospital.id, { posts: [], loading: true });
  try {
    const data = await authorizedFetch(`/api/reviews?${new URLSearchParams({ hospitalId: hospital.id })}`);
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

async function unpublishReview(button) {
  const subject = state.user?.sub;
  button.disabled = true;
  try {
    const data = await authorizedFetch(`/api/reviews?${new URLSearchParams({ visitId: button.dataset.unpublish })}`, { method: "DELETE" });
    if (state.user?.sub !== subject) return;
    state.visits = state.visits.map((visit) => visit.id === data.visit.id ? data.visit : visit);
    state.reviewFeeds.clear();
    renderCalendar();
  } catch (error) {
    $("#accountStatus").textContent = error.message;
    button.disabled = false;
  }
}

function updateStatus() {
  const pill = $("#visitStatus");
  if (!state.activeVisit) {
    pill.textContent = "受診予定なし";
    return;
  }
  const label = state.activeVisit.status === "planned" ? "移動中" : "計測中";
  pill.textContent = `${label}: ${state.activeVisit.hospitalName}`;
}

function activeVisitStorageKey() {
  return `campusClinicActiveVisit:${state.user.sub}`;
}

function loadActiveVisit() {
  if (!state.user) return;
  try {
    state.activeVisit = JSON.parse(localStorage.getItem(activeVisitStorageKey()) || "null");
  } catch {
    state.activeVisit = null;
  }
}

function saveActiveVisit() {
  if (state.user) localStorage.setItem(activeVisitStorageKey(), JSON.stringify(state.activeVisit));
}

function bindEvents() {
  $("#signupButton").addEventListener("click", async () => {
    if (!state.authClient) return;
    try {
      await state.authClient.loginWithRedirect({ authorizationParams: { screen_hint: "signup" } });
    } catch (error) {
      $("#accountStatus").textContent = error.message;
    }
  });
  $("#universitySearch").addEventListener("input", () => {
    $("#universitySelect").value = "";
    $("#universitySelection").textContent = "";
    $("#universitySearch").setCustomValidity("候補から大学を選択してください。");
    renderUniversityOptions();
  });
  $("#universitySearch").addEventListener("focus", renderUniversityOptions);
  $("#universitySearch").addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    if (event.key === "Escape") closeUniversityOptions();
    const buttons = [...$("#universitySuggestions").querySelectorAll("button")];
    if ($("#universitySuggestions").hidden || !buttons.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      state.universityOptionIndex = (state.universityOptionIndex + direction + buttons.length) % buttons.length;
      buttons.forEach((button, index) => button.setAttribute("aria-selected", String(index === state.universityOptionIndex)));
      const active = buttons[state.universityOptionIndex];
      $("#universitySearch").setAttribute("aria-activedescendant", active.id);
      active.scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter" && state.universityOptionIndex >= 0) {
      event.preventDefault();
      buttons[state.universityOptionIndex].click();
    } else if (event.key === "Tab") closeUniversityOptions();
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".university-picker")) closeUniversityOptions();
  });
  $("#profileForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.target.querySelector('button[type="submit"]');
    const subject = state.user?.sub;
    if (button.disabled || !subject) return;
    if (!$("#universitySelect").value) {
      $("#universitySearch").setCustomValidity("候補から大学を選択してください。");
      $("#universitySearch").reportValidity();
      return;
    }
    button.disabled = true;
    try {
      const data = await authorizedFetch("/api/profile", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ universityId: $("#universitySelect").value,
          grade: $("#profileGrade").value, gender: $("#profileGender").value }),
      });
      if (state.user?.sub !== subject) return;
      state.profile = data.profile;
      await enterApplication();
      navigate("search");
    } catch (error) {
      $("#accountStatus").textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
  $("#loginButton").addEventListener("click", async () => {
    if (!state.authClient) return;
    try {
      await state.authClient.loginWithRedirect();
    } catch (error) {
      $("#accountStatus").textContent = error.message;
    }
  });
  const logout = async () => {
    const client = state.authClient;
    state.user = null;
    state.profile = null;
    state.universityLocation = null;
    state.currentLocation = null;
    $("#originType").value = "university";
    state.visits = [];
    state.reviewFeeds.clear();
    state.activeVisit = null;
    state.selectedHospital = null;
    $("#detail").innerHTML = "";
    renderActiveVisit();
    renderCalendar();
    updateStatus();
    navigate("search");
    $("#accountStatus").textContent = "";
    $("#logoutButton").hidden = true;
    $("#loginButton").hidden = false;
    updateAccessScreen();
    try {
      await client.logout({ logoutParams: { returnTo: `${location.origin}/` } });
    } catch (error) {
      $("#accountStatus").textContent = error.message;
    }
  };
  $("#logoutButton").addEventListener("click", logout);
  $("#profileLogoutButton").addEventListener("click", logout);
  $("#searchForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.user || !state.profile) return;
    if (!await ensureSearchOrigin()) return;
    navigate("results");
    try {
      await renderResults();
    } catch (error) {
      $("#accountStatus").textContent = error.message;
    }
  });

  document.querySelectorAll("[data-when]").forEach((button) => {
    button.addEventListener("click", () => {
      const isScheduled = button.dataset.when === "time";
      $("#when").value = button.dataset.when;
      $("#scheduledTimeField").hidden = !isScheduled;
      document.querySelectorAll("[data-when]").forEach((item) => {
        const isActive = item === button;
        item.classList.toggle("active", isActive);
        item.setAttribute("aria-pressed", String(isActive));
      });
      if (isScheduled) $("#startTime").focus();
    });
  });

  $("#originType").addEventListener("change", () => {
    const usesCurrentLocation = $("#originType").value === "current";
    updateLocationStatus(usesCurrentLocation
      ? "検索時に位置情報の許可が必要です"
      : `${state.profile.universityName}の登録所在地から検索します`);
  });

  document.body.addEventListener("click", (event) => {
    const detailButton = event.target.closest("[data-detail]");
    const planButton = event.target.closest("[data-plan]");
    const navButton = event.target.closest("[data-nav]");
    const dateButton = event.target.closest("[data-date]");
    const recordViewButton = event.target.closest("[data-record-view]");
    const unpublishButton = event.target.closest("[data-unpublish]");

    if (unpublishButton) unpublishReview(unpublishButton);
    if (event.target.closest("[data-retry-reviews]") && state.selectedHospital) renderDetail(state.selectedHospital.id);
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
    if (event.target.id === "manualTimeForm") applyManualTimes(event);
  });

  document.body.addEventListener("input", (event) => {
    if (!state.activeVisit || !event.target.closest("#completionForm")) return;
    readCompletionDraft();
    updateReviewPreview();
    saveActiveVisit();
  });

  document.body.addEventListener("click", (event) => {
    if (event.target.id === "arrivalButton") markArrival();
    if (event.target.id === "leaveButton") markLeave();
  });

  document.querySelectorAll(".seg").forEach((button) => {
    button.addEventListener("click", () => {
      state.view = button.dataset.view;
      document.querySelectorAll(".seg").forEach((item) => item.classList.toggle("active", item === button));
      $("#results").hidden = state.view !== "list";
      $("#mapView").hidden = state.view !== "map";
      if (state.view === "map") refreshResultMapSize();
    });
  });

  $("#prevMonth").addEventListener("click", () => {
    state.calendarDate = new Date(state.calendarDate.getFullYear(), state.calendarDate.getMonth() - 1, 1);
    renderCalendar();
  });

  $("#nextMonth").addEventListener("click", () => {
    state.calendarDate = new Date(state.calendarDate.getFullYear(), state.calendarDate.getMonth() + 1, 1);
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
  state.calendarDate = new Date(latestDate.getFullYear(), latestDate.getMonth(), 1);
}

function init() {
  setDefaultSearchTimes();
  bindEvents();
  renderActiveVisit();
  renderCalendar();
  updateStatus();
  initializeAuth();
}

init();
