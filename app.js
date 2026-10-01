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

const origins = {
  imadegawa: { label: "同志社大学 今出川", latitude: 35.0299, longitude: 135.7608 },
  miyazaki: { label: "宮崎大学 木花", latitude: 31.8310233, longitude: 131.4125839 },
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

const communityPosts = [
  {
    id: "review-1",
    hospitalName: "青葉クリニック",
    department: "internal",
    visitedAt: "9月28日 14時ごろ",
    stayMinutes: 42,
    feeAmount: 1840,
    reservationStatus: "予約なし",
    waitingImpression: "スムーズ",
    note: "受付から会計まで案内が分かりやすく、思ったより早く終わりました。",
    helpful: 12,
  },
  {
    id: "review-2",
    hospitalName: "烏丸駅前メディカル",
    department: "ent",
    visitedAt: "9月27日 17時ごろ",
    stayMinutes: 58,
    feeAmount: 2260,
    reservationStatus: "予約あり",
    waitingImpression: "普通",
    note: "夕方は少し混んでいました。予約時間から15分ほどで呼ばれました。",
    helpful: 8,
  },
  {
    id: "review-3",
    hospitalName: "鴨川皮ふ科",
    department: "dermatology",
    visitedAt: "9月26日 11時ごろ",
    stayMinutes: 67,
    feeAmount: 1980,
    reservationStatus: "予約なし",
    waitingImpression: "待った",
    note: "午前中は混雑していました。時間に余裕がある日に行くと安心です。",
    helpful: 19,
  },
  {
    id: "review-4",
    hospitalName: "みどりヶ丘眼科",
    department: "eye",
    visitedAt: "9月24日 10時ごろ",
    stayMinutes: 35,
    feeAmount: 1320,
    reservationStatus: "予約あり",
    waitingImpression: "スムーズ",
    note: "予約して行ったので、検査を含めても短時間で終わりました。",
    helpful: 6,
  },
  {
    id: "review-5",
    hospitalName: "さくらウィメンズクリニック",
    department: "gynecology",
    visitedAt: "9月22日 15時ごろ",
    stayMinutes: 51,
    feeAmount: 3100,
    reservationStatus: "予約あり",
    waitingImpression: "普通",
    note: "院内は落ち着いていました。会計まで少し待ちました。",
    helpful: 10,
  },
  {
    id: "review-6",
    hospitalName: "青葉クリニック",
    department: "dermatology",
    visitedAt: "9月21日 10時ごろ",
    stayMinutes: 36,
    feeAmount: 2150,
    reservationStatus: "予約なし",
    waitingImpression: "スムーズ",
    note: "平日の午前に行きました。受付後すぐに案内され、会計も早かったです。",
    helpful: 7,
  },
  {
    id: "review-7",
    hospitalName: "烏丸駅前メディカル",
    department: "internal",
    visitedAt: "9月19日 13時ごろ",
    stayMinutes: 31,
    feeAmount: 1680,
    reservationStatus: "予約なし",
    waitingImpression: "スムーズ",
    note: "昼すぎは比較的空いていて、次の授業までに余裕をもって戻れました。",
    helpful: 15,
  },
];

const state = {
  view: "list",
  recordView: "month",
  selectedHospital: null,
  activeVisit: null,
  calendarDate: new Date(),
  selectedDate: dateKey(new Date()),
  visits: loadVisits(),
  helpfulReviews: new Set(),
  currentLocation: null,
  routeTimes: new Map(),
  routeCache: new Map(),
  resultMap: null,
  resultMapBounds: null,
};

const $ = (selector) => document.querySelector(selector);

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
  return origins[originType];
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
    facilityType: $("#facilityType").value,
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

function updateFacilityTypeUI() {
  const isPharmacy = $("#facilityType").value === "pharmacy";
  $("#departmentField").hidden = isPharmacy;
  $(".search-submit").textContent = isPharmacy ? "薬局を検索する" : "病院・診療所を検索する";
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

async function ensureSearchOrigin() {
  if ($("#originType").value !== "current" || state.currentLocation) return true;
  const button = $(".search-submit");
  const previousLabel = button.textContent;
  button.disabled = true;
  button.textContent = "現在地を取得しています";
  $("#locationStatus").textContent = "位置情報を確認しています…";
  try {
    state.currentLocation = await getCurrentLocation();
    $("#locationStatus").textContent = "現在地を取得しました";
    return true;
  } catch (error) {
    $("#locationStatus").textContent = error.message;
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
    type: context.facilityType,
  });
  if (context.facilityType !== "pharmacy") {
    parameters.set("department", context.department);
  }

  try {
    const response = await fetch(`/api/facilities?${parameters}`);
    if (!response.ok) throw new Error(`施設API ${response.status}`);
    const data = await response.json();
    hospitals = Array.isArray(data.facilities) ? data.facilities : [];
    return true;
  } catch (error) {
    console.warn("Facility API lookup failed", error);
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
  const { facilityType, department } = getSearchContext();
  return hospitals
    .filter((hospital) => {
      if (getFacilityDistance(hospital) > 12) return false;
      if (facilityType === "pharmacy") return hospital.type === "pharmacy";
      return hospital.type !== "pharmacy" && hospital.departments.includes(department);
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
  const targetLabel = context.facilityType === "pharmacy" ? "薬局" : departments[context.department];
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
          <span class="section-kicker">匿名の受診記録</span>
          <h3 id="reviews-title">みんなの口コミ</h3>
        </div>
        <strong>${communityPosts.filter((post) => post.hospitalName === hospital.name).length}件</strong>
      </div>
      <div class="community-feed" id="hospitalReviews">
        ${renderReviewCards(hospital)}
      </div>
    </section>
  `;
  navigate("detail");
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
        <h3>${visit.hospitalName}</h3>
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
}

function completionFields(visit) {
  return `
    <form class="completion-form" id="completionForm">
      <label>費用
        <input id="feeAmount" type="number" min="0" step="10" value="${visit.feeAmount}" placeholder="1840" />
      </label>
      <label>予約
        <select id="reservationStatus">
          <option ${visit.reservationStatus === "予約あり" ? "selected" : ""}>予約あり</option>
          <option ${visit.reservationStatus === "予約なし" ? "selected" : ""}>予約なし</option>
        </select>
      </label>
      <label>待ち時間
        <select id="waitingImpression">
          <option ${visit.waitingImpression === "スムーズ" ? "selected" : ""}>スムーズ</option>
          <option ${visit.waitingImpression === "普通" ? "selected" : ""}>普通</option>
          <option ${visit.waitingImpression === "待った" ? "selected" : ""}>待った</option>
        </select>
      </label>
      <button class="primary-button" type="submit">記録を保存</button>
    </form>
  `;
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

function completeVisit(event) {
  event.preventDefault();
  state.activeVisit.feeAmount = $("#feeAmount").value;
  state.activeVisit.reservationStatus = $("#reservationStatus").value;
  state.activeVisit.waitingImpression = $("#waitingImpression").value;
  state.activeVisit.stayMinutes = stayMinutes(state.activeVisit);
  state.activeVisit.userConfirmed = true;
  state.activeVisit.completedAt = new Date().toISOString();
  state.visits.push(state.activeVisit);
  state.activeVisit = null;
  localStorage.removeItem("campusClinicActiveVisit");
  saveVisits();
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
          <h4>${visit.hospitalName}</h4>
        </div>
        <strong class="stay-time">${duration}<small>分</small></strong>
      </header>
      <dl>
        <div><dt>受診時間</dt><dd>${formatTime(visit.arrivalAt)}〜${formatTime(visit.leaveAt)}</dd></div>
        <div><dt>費用</dt><dd>${visit.feeAmount ? formatCurrency(Number(visit.feeAmount)) : "未入力"}</dd></div>
        <div><dt>予約</dt><dd>${visit.reservationStatus}</dd></div>
        <div><dt>待ち時間</dt><dd>${visit.waitingImpression}</dd></div>
      </dl>
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

function renderReviewCards(hospital) {
  const posts = communityPosts.filter((post) => post.hospitalName === hospital.name);
  if (!posts.length) {
    return `
      <div class="empty-record">
        <strong>この病院の口コミはまだありません</strong>
        <span>受診記録が集まると、ここに匿名で表示されます。</span>
      </div>
    `;
  }

  return posts.map((post) => {
    const selected = state.helpfulReviews.has(post.id);
    const helpfulCount = post.helpful + (selected ? 1 : 0);
    return `
      <article class="community-card">
        <header class="community-card-header">
          <div>
            <span class="department-label">${departments[post.department]}</span>
            <h3>${post.hospitalName}</h3>
            <span class="review-date">${post.visitedAt}・匿名</span>
          </div>
          <div class="community-stay"><strong>${post.stayMinutes}</strong><span>分滞在</span></div>
        </header>
        <div class="review-facts">
          <div><span>費用</span><strong>${formatCurrency(post.feeAmount)}</strong></div>
          <div><span>予約</span><strong>${post.reservationStatus}</strong></div>
          <div><span>待ち時間</span><strong>${post.waitingImpression}</strong></div>
        </div>
        <p class="review-note">${post.note}</p>
        <button class="helpful-button ${selected ? "selected" : ""}" type="button" data-helpful="${post.id}" aria-pressed="${selected}">
          参考になった <span>${helpfulCount}</span>
        </button>
      </article>
    `;
  }).join("");
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

function loadVisits() {
  try {
    return JSON.parse(localStorage.getItem("campusClinicVisits") || "[]");
  } catch {
    return [];
  }
}

function loadActiveVisit() {
  try {
    state.activeVisit = JSON.parse(localStorage.getItem("campusClinicActiveVisit") || "null");
  } catch {
    state.activeVisit = null;
  }
}

function saveVisits() {
  localStorage.setItem("campusClinicVisits", JSON.stringify(state.visits));
}

function saveActiveVisit() {
  localStorage.setItem("campusClinicActiveVisit", JSON.stringify(state.activeVisit));
}

function bindEvents() {
  $("#searchForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!await ensureSearchOrigin()) return;
    navigate("results");
    await renderResults();
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

  $("#facilityType").addEventListener("change", updateFacilityTypeUI);
  $("#originType").addEventListener("change", () => {
    const usesCurrentLocation = $("#originType").value === "current";
    $("#locationStatus").textContent = usesCurrentLocation
      ? "検索時に位置情報の許可が必要です"
      : "検索時にOSRMで道路経路を計算します";
  });

  document.body.addEventListener("click", (event) => {
    const detailButton = event.target.closest("[data-detail]");
    const planButton = event.target.closest("[data-plan]");
    const navButton = event.target.closest("[data-nav]");
    const dateButton = event.target.closest("[data-date]");
    const helpfulButton = event.target.closest("[data-helpful]");
    const recordViewButton = event.target.closest("[data-record-view]");

    if (detailButton) renderDetail(detailButton.dataset.detail);
    if (planButton) planVisit(planButton.dataset.plan);
    if (navButton) navigate(navButton.dataset.nav);
    if (recordViewButton) {
      state.recordView = recordViewButton.dataset.recordView;
      renderRecordView();
    }
    if (helpfulButton) {
      const reviewId = helpfulButton.dataset.helpful;
      if (state.helpfulReviews.has(reviewId)) state.helpfulReviews.delete(reviewId);
      else state.helpfulReviews.add(reviewId);
      if (state.selectedHospital && $("#hospitalReviews")) {
        $("#hospitalReviews").innerHTML = renderReviewCards(state.selectedHospital);
      }
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

function seedDemoVisit() {
  if (state.visits.length) return;
  const date = new Date();
  date.setDate(date.getDate() - 2);
  date.setHours(13, 8, 0, 0);
  const leave = new Date(date);
  leave.setMinutes(leave.getMinutes() + 44);
  state.visits.push({
    id: "demo",
    hospitalId: "aoba",
    hospitalName: "青葉クリニック",
    department: "internal",
    status: "completed",
    plannedAt: date.toISOString(),
    arrivalAt: date.toISOString(),
    leaveAt: leave.toISOString(),
    stayMinutes: 44,
    feeAmount: "1840",
    reservationStatus: "予約なし",
    waitingImpression: "普通",
    userConfirmed: true,
  });
  saveVisits();
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
  loadActiveVisit();
  seedDemoVisit();
  selectLatestVisit();
  setDefaultSearchTimes();
  updateFacilityTypeUI();
  bindEvents();
  renderActiveVisit();
  renderCalendar();
  updateStatus();
}

init();
