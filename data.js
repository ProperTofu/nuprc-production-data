// data.js — NUPRC Dashboard Data Layer
// Dev: run `npx serve .` locally; push to GitHub Pages for live deployment

const OIL_YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026];
const GAS_YEARS = [2021, 2022, 2023, 2024, 2025, 2026];

const MONTH_ORDER = [
  'JANUARY','FEBRUARY','MARCH','APRIL','MAY','JUNE',
  'JULY','AUGUST','SEPTEMBER','OCTOBER','NOVEMBER','DECEMBER'
];

window.OIL_YEARS    = OIL_YEARS;
window.GAS_YEARS    = GAS_YEARS;
window.MONTH_ORDER  = MONTH_ORDER;
window.allOilRows   = [];
window.allGasRows   = [];
window._nuprcReady  = false;

function normalizeTerminal(name) {
  if (!name) return '';
  const n = name.trim();
  if (n === 'OTAKPIPO (Ex Ima Terminal)') return 'OTAKPIPO';
  // AJAPA (Atala Oil) normalises to AJAPA — note this may differ from plain AJAPA in later years
  if (n === 'AJAPA (Atala Oil)') return 'AJAPA';
  // OYO / OBODO left as-is (combined reporting entity, not a rename of OYO)
  return n;
}

(function loadAllData() {
  function parseCSV(url) {
    return new Promise(function(resolve) {
      Papa.parse(url, {
        download: true,
        header: true,
        dynamicTyping: true,
        skipEmptyLines: true,
        complete: resolve,
        error: resolve   // always resolve so Promise.all never stalls
      });
    });
  }

  const oilPromises = OIL_YEARS.map(year =>
    parseCSV(`oil_${year}.csv`).then(result => {
      if (!result || !result.data) return;
      result.data.forEach(r => {
        if (!r.month || !r.terminal) return;
        window.allOilRows.push({
          year,
          month:       String(r.month).toUpperCase().trim(),
          terminal:    normalizeTerminal(r.terminal),
          liquid_type: String(r.liquid_type || '').trim(),
          volume_bbls: Number(r.volume_bbls) || 0
        });
      });
    })
  );

  const gasPromises = GAS_YEARS.map(year =>
    parseCSV(`gas_${year}.csv`).then(result => {
      if (!result || !result.data) return;
      result.data.forEach(r => {
        if (!r.month) return;
        window.allGasRows.push({
          year,
          month:    String(r.month).toUpperCase().trim(),
          ag:       Number(r.ag_production_mmscf)      || 0,
          nag:      Number(r.nag_production_mmscf)     || 0,
          produced: Number(r.total_gas_produced_mmscf) || 0,
          fieldUse: Number(r.field_use_mmscf)          || 0,
          domestic: Number(r.domestic_sales_mmscf)     || 0,
          export:   Number(r.export_sales_mmscf)       || 0,
          utilized: Number(r.total_gas_utilized_mmscf) || 0,
          flared:   Number(r.total_gas_flared_mmscf)   || 0
        });
      });
    })
  );

  Promise.all([...oilPromises, ...gasPromises]).then(function() {
    setTimeout(function() {
      window._nuprcReady = true;
      console.log(
        `[NUPRC] Ready — ${window.allOilRows.length} oil rows, ` +
        `${window.allGasRows.length} gas rows`
      );
      document.dispatchEvent(new Event('nuprcDataReady'));
    }, 0);
  });
})();

// ── Helpers ───────────────────────────────────────────────────────

function getOilData(year, liquidType, terminal) {
  return window.allOilRows.filter(r => {
    if (year       && r.year        !== year)       return false;
    if (liquidType && r.liquid_type !== liquidType) return false;
    if (terminal   && r.terminal    !== terminal)   return false;
    return true;
  });
}

function getGasData(year) {
  return window.allGasRows.filter(r => !year || r.year === year);
}

function getTerminals() {
  const totals = {};
  window.allOilRows.forEach(r => {
    totals[r.terminal] = (totals[r.terminal] || 0) + r.volume_bbls;
  });
  return Object.keys(totals).sort((a, b) => totals[b] - totals[a]);
}

function getYears() { return OIL_YEARS; }

function sumField(rows, field) {
  return rows.reduce((s, r) => s + (r[field] || 0), 0);
}

// ── Formatters ────────────────────────────────────────────────────

function fmtBn(v)   { return (v / 1e9).toFixed(2) + 'bn'; }
function fmtTn(v)   { return (v / 1e6).toFixed(2) + ' Tn'; }
function fmtM(v)    { return (v / 1e6).toFixed(1); }
function fmtBopd(v) { return (v / 1e6).toFixed(2) + 'M'; }
function fmtPct(v)  { return v.toFixed(1) + '%'; }
function fmtComma(v) {
  if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
  if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K';
  return v.toFixed(0);
}

window.getOilData   = getOilData;
window.getGasData   = getGasData;
window.getTerminals = getTerminals;
window.getYears     = getYears;
window.sumField     = sumField;
window.fmtBn        = fmtBn;
window.fmtTn        = fmtTn;
window.fmtM         = fmtM;
window.fmtBopd      = fmtBopd;
window.fmtPct       = fmtPct;
window.fmtComma     = fmtComma;
