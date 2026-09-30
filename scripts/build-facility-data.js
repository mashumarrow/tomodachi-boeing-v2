const fs = require("fs");
const path = require("path");
const readline = require("readline");

const root = path.resolve(__dirname, "..");
const dbDir = path.join(root, "db");
const outputDir = path.join(root, "data");
const outputFile = path.join(outputDir, "facilities.js");

const campuses = {
  imadegawa: { latitude: 35.0299, longitude: 135.7608 },
  miyazaki: { latitude: 31.8310233, longitude: 131.4125839 },
};
const maxDistanceKm = 12;
const facilities = new Map();

function parseCsvLine(line) {
  const values = [];
  let value = "";
  let quoted = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"') {
      if (quoted && line[index + 1] === '"') {
        value += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (char === "," && !quoted) {
      values.push(value);
      value = "";
    } else {
      value += char;
    }
  }

  if (quoted) throw new Error("改行を含むCSVレコードには対応していません。");
  values.push(value);
  return values;
}

async function eachCsvRow(fileName, callback) {
  const input = fs.createReadStream(path.join(dbDir, fileName), { encoding: "utf8" });
  const lines = readline.createInterface({ input, crlfDelay: Infinity });
  let firstLine = true;
  for await (const line of lines) {
    if (firstLine) {
      firstLine = false;
      continue;
    }
    if (line) callback(parseCsvLine(line));
  }
}

function distanceKm(origin, latitude, longitude) {
  const toRadians = (value) => (value * Math.PI) / 180;
  const earthRadius = 6371;
  const latitudeDelta = toRadians(latitude - origin.latitude);
  const longitudeDelta = toRadians(longitude - origin.longitude);
  const a = Math.sin(latitudeDelta / 2) ** 2
    + Math.cos(toRadians(origin.latitude)) * Math.cos(toRadians(latitude))
    * Math.sin(longitudeDelta / 2) ** 2;
  return earthRadius * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function mapDepartment(name) {
  if (name.includes("皮膚")) return "dermatology";
  if (name.includes("眼")) return "eye";
  if (name.includes("耳鼻") || name.includes("耳鼻咽喉")) return "ent";
  if (name.includes("婦人") || name.includes("産婦人")) return "gynecology";
  if (name.includes("内科")) return "internal";
  return null;
}

function mapPosition(latitude, longitude) {
  const campus = campuses.imadegawa;
  return {
    x: Math.max(8, Math.min(92, 50 + (longitude - campus.longitude) * 420)),
    y: Math.max(8, Math.min(92, 50 - (latitude - campus.latitude) * 520)),
  };
}

function normalizeUrl(value) {
  if (!value) return "";
  return /^https?:\/\//i.test(value) ? value : `https://${value}`;
}

function addMedicalFacility(row, kind) {
  const latitude = Number(row[10]);
  const longitude = Number(row[11]);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
  const campusDistances = Object.fromEntries(Object.entries(campuses).map(([key, campus]) => [
    key,
    Number(distanceKm(campus, latitude, longitude).toFixed(2)),
  ]));
  const distance = Math.min(...Object.values(campusDistances));
  if (distance > maxDistanceKm) return;

  const key = `${kind}:${row[0]}`;
  const position = mapPosition(latitude, longitude);
  facilities.set(key, {
    id: key,
    sourceId: row[0],
    type: kind,
    name: row[1],
    address: row[9],
    latitude,
    longitude,
    distanceKm: Number(distance.toFixed(2)),
    campusDistances,
    departments: new Set(),
    openingTimes: [],
    website: normalizeUrl(row[12]),
    maps: `https://www.google.com/maps/search/?api=1&query=${latitude},${longitude}`,
    baseTravel: Math.max(3, Math.round((distance / 4.5) * 60)),
    medianWait: kind === "hospital" ? 60 : 35,
    samples: 0,
    feeLow: null,
    feeHigh: null,
    p60: null,
    p90: null,
    phone: "掲載なし",
    x: position.x,
    y: position.y,
  });
}

function addSpeciality(row, kind) {
  const facility = facilities.get(`${kind}:${row[0]}`);
  if (!facility) return;
  const department = mapDepartment(row[2] || "");
  if (department) facility.departments.add(department);

  for (let index = 4; index <= 18; index += 2) {
    if (row[index] && row[index + 1]) {
      facility.openingTimes.push([row[index], row[index + 1]]);
    }
  }
}

function addPharmacy(row) {
  const latitude = Number(row[8]);
  const longitude = Number(row[9]);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
  const campusDistances = Object.fromEntries(Object.entries(campuses).map(([key, campus]) => [
    key,
    Number(distanceKm(campus, latitude, longitude).toFixed(2)),
  ]));
  const distance = Math.min(...Object.values(campusDistances));
  if (distance > maxDistanceKm) return;

  const position = mapPosition(latitude, longitude);
  const openingTimes = [];
  for (let index = 64; index < row.length; index += 2) {
    if (row[index] && row[index + 1]) openingTimes.push([row[index], row[index + 1]]);
  }
  facilities.set(`pharmacy:${row[0]}`, {
    id: `pharmacy:${row[0]}`,
    sourceId: row[0],
    type: "pharmacy",
    name: row[1],
    address: row[7],
    latitude,
    longitude,
    distanceKm: Number(distance.toFixed(2)),
    campusDistances,
    departments: new Set(["pharmacy"]),
    openingTimes,
    website: normalizeUrl(row[10]),
    maps: `https://www.google.com/maps/search/?api=1&query=${latitude},${longitude}`,
    baseTravel: Math.max(3, Math.round((distance / 4.5) * 60)),
    medianWait: 15,
    samples: 0,
    feeLow: null,
    feeHigh: null,
    p60: null,
    p90: null,
    phone: "掲載なし",
    x: position.x,
    y: position.y,
  });
}

function summarizeHours(openingTimes) {
  if (!openingTimes.length) return "診療時間は詳細で確認";
  const starts = openingTimes.map(([start]) => start).sort();
  const ends = openingTimes.map(([, end]) => end).sort();
  return `${starts[0]}-${ends[ends.length - 1]}`;
}

async function main() {
  await eachCsvRow("01-1_hospital_facility_info_20260601.csv", (row) => addMedicalFacility(row, "hospital"));
  await eachCsvRow("02-1_clinic_facility_info_20260601.csv", (row) => addMedicalFacility(row, "clinic"));
  await eachCsvRow("01-2_hospital_speciality_hours_20260601.csv", (row) => addSpeciality(row, "hospital"));
  await eachCsvRow("02-2_clinic_speciality_hours_20260601.csv", (row) => addSpeciality(row, "clinic"));
  await eachCsvRow("05_pharmacy_20260601.csv", addPharmacy);

  const output = [...facilities.values()]
    .filter((facility) => facility.type === "pharmacy" || facility.departments.size > 0)
    .map((facility) => ({
      ...facility,
      departments: [...facility.departments],
      open: summarizeHours(facility.openingTimes),
      openingTimes: undefined,
      sourceId: undefined,
    }))
    .sort((a, b) => a.distanceKm - b.distanceKm);

  fs.mkdirSync(outputDir, { recursive: true });
  fs.writeFileSync(outputFile, `window.FACILITY_DATA = ${JSON.stringify(output)};\n`, "utf8");

  const counts = output.reduce((result, facility) => {
    result[facility.type] += 1;
    return result;
  }, { hospital: 0, clinic: 0, pharmacy: 0 });
  process.stdout.write(`Generated ${output.length} facilities: ${JSON.stringify(counts)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack}\n`);
  process.exitCode = 1;
});
