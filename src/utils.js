/**
 * Utility and business logic functions extracted from the dashboard.
 * These are pure functions suitable for unit testing.
 */

// --- Formatters ---

const fmtMoney = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const fmtPct = new Intl.NumberFormat("en-US", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 });
const fmtNum = new Intl.NumberFormat("en-US");

function shortMoney(value) {
  const n = Number(value) || 0;
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 1000000000) return sign + "$" + (abs / 1000000000).toFixed(1) + "B";
  if (abs >= 1000000) return sign + "$" + (abs / 1000000).toFixed(1) + "M";
  if (abs >= 1000) return sign + "$" + (abs / 1000).toFixed(0) + "K";
  return sign + fmtMoney.format(abs);
}

function formatPct(value) {
  const n = Number(value) || 0;
  return fmtPct.format(Math.abs(n) > 1 ? n / 100 : n);
}

function formatKpi(value, kind) {
  if (kind === "money") return shortMoney(value);
  if (kind === "pct") return formatPct(value);
  if (kind === "num") return fmtNum.format(Number(value) || 0);
  return escapeHtml(value);
}

function shortLabel(value, max) {
  const text = String(value || "");
  return text.length > max ? text.slice(0, max - 1) + "." : text;
}

function csvValue(value) {
  const text = String(value == null ? "" : value).replaceAll('"', '""');
  return /[",\n]/.test(text) ? `"${text}"` : text;
}

function formatRangeValue(value, label) {
  const n = Number(value);
  if (/revenue|spend|staffing|rent|cost|collection|marketing|fee|patient/i.test(label) && n >= 1000) return shortMoney(n);
  if (/%|margin|rate|adoption|close/i.test(label)) return n + "%";
  return fmtNum.format(n);
}

// --- HTML/Security ---

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

// --- Date Helpers ---

function daysBetween(start, end) {
  const a = new Date(start + "T00:00:00");
  const b = new Date(end + "T00:00:00");
  return Math.floor((b - a) / 86400000);
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function daysOverdue(dueDate, status) {
  if (!dueDate || /complete|cancelled/i.test(status || "")) return 0;
  return Math.max(0, daysBetween(dueDate, todayIso()));
}

// --- Math/Data Helpers ---

function sum(rows, key) {
  return rows.reduce((total, row) => total + (typeof key === "function" ? Number(key(row) || 0) : Number(row[key] || 0)), 0);
}

function average(rows, key) {
  if (!rows.length) return 0;
  return sum(rows, key) / rows.length;
}

function countBy(rows, key) {
  return rows.reduce((acc, row) => {
    const value = row[key] || "Unknown";
    acc[value] = (acc[value] || 0) + 1;
    return acc;
  }, {});
}

function groupSum(rows, groupKey, sumKey) {
  return rows.reduce((acc, row) => {
    const group = row[groupKey] || "Unknown";
    acc[group] = (acc[group] || 0) + Number(row[sumKey] || 0);
    return acc;
  }, {});
}

function normalize(value, min, max) {
  return clamp((Number(value) - min) / (max - min), 0, 1);
}

function safeDivide(a, b) {
  return b ? Number(a || 0) / Number(b || 0) : 0;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function loanPayment(principal, monthlyRate, months) {
  if (!principal || !months) return 0;
  if (!monthlyRate) return principal / months;
  return principal * monthlyRate / (1 - Math.pow(1 + monthlyRate, -months));
}

function getValue(row, key) {
  return typeof key === "function" ? key(row) : row[key];
}

// --- Business Logic / Scoring ---

function taskPriorityScore(t) {
  const priority = { Critical: 38, High: 28, Medium: 18, Low: 8 }[t.priority] || 10;
  const overdue = Math.max(0, daysOverdue(t.dueDate, t.status)) * 3;
  const impact = Math.min(28, (Number(t.financialImpact) || 0) / 35000);
  const dep = Number(t.dependencyImportance) || 0;
  const risk = /blocked/i.test(t.status) ? 12 : /waiting/i.test(t.status) ? 6 : 0;
  return Math.round(clamp(priority + overdue + impact + dep + risk, 0, 100));
}

function pcpAcquisitionScore(l) {
  const score =
    normalize(l.ebitdaMargin, .05, .25) * 18 +
    normalize(l.estimatedRevenue, 1000000, 7000000) * 10 +
    normalize(l.medicarePct, .25, .65) * 12 +
    normalize(l.ownerMotivation, 1, 10) * 9 +
    normalize(l.successionIssue, 1, 10) * 9 +
    (1 - normalize(l.valuationMultiple || safeDivide(l.askingPrice, l.estimatedEbitda), 3, 7)) * 10 +
    normalize(l.strategicFit, 40, 100) * 12 +
    normalize(l.financialFit, 30, 100) * 10 +
    normalize(l.clinicalFit, 40, 100) * 6 +
    normalize(l.dataQuality, 20, 100) * 4;
  return Math.round(clamp(score, 0, 100));
}

function pcpStartupScore(m) {
  const medicareDensity = safeDivide(m.medicareLives, m.population);
  const shortage = safeDivide(m.population, Math.max(1, m.competingPcps));
  const rentAffordability = 1 - normalize(m.rent, 7000, 22000);
  const competition = 1 - normalize(m.competingPcps + m.urgentCares * 2, 20, 160);
  const ancillary = normalize(m.ancillaryAdoption, .12, .45);
  const credentialing = 1 - normalize(m.credentialingMonths, 4, 8);
  const score = normalize(medicareDensity, .12, .28) * 20 + normalize(shortage, 2200, 6500) * 18 + rentAffordability * 14 + competition * 14 + ancillary * 12 + credentialing * 8 + normalize(m.hospitals, 1, 6) * 6 + normalize(m.newPatientsPerMonth, 50, 150) * 8;
  return Math.round(clamp(score, 0, 100));
}

function clinicalTrialScore(t) {
  const progress = safeDivide(t.enrolled, t.enrollmentTarget);
  const margin = t.projectedMargin || 0;
  const revenue = normalize(t.netProjectedRevenue, 150000, 550000);
  const stageBonus = /active|enrolling|recruiting|selected/i.test(t.stage) ? 15 : /lead|sent/i.test(t.stage) ? 5 : 10;
  const screenPenalty = safeDivide(t.screenFailures, Math.max(1, t.screenFailures + t.enrolled)) * 12;
  return Math.round(clamp(revenue * 24 + normalize(margin, .15, .4) * 26 + progress * 22 + stageBonus - screenPenalty + normalize(t.enrollmentTarget, 20, 120) * 13, 0, 100));
}

function trialSiteScore(s) {
  return Math.round(clamp(normalize(s.patientDatabase, 7000, 60000) * 20 + normalize(s.piCount, 1, 8) * 15 + normalize(s.coordinatorCount, 1, 12) * 12 + normalize(s.activeStudies, 1, 14) * 16 + normalize(s.ebitda / Math.max(1, s.annualRevenue), .05, .35) * 17 + normalize(s.qualityScore, 50, 95) * 10 + normalize(s.croRelationships, 40, 95) * 10, 0, 100));
}

function stateCombinedScore(s) {
  if (!s) return 0;
  const riskPenalty = (s.cpomRisk === "High" ? 12 : s.cpomRisk === "Medium" ? 5 : 0) + (s.licensingComplexity === "High" ? 8 : 3);
  return Math.round(clamp((s.pcpOpportunityScore + s.trialsOpportunityScore + s.medicareOpportunity + s.ruralOpportunity + s.trialRecruitmentPotential) / 5 - riskPenalty, 0, 100));
}

function enrichPcpLead(l) {
  const ebitdaMargin = safeDivide(l.estimatedEbitda, l.estimatedRevenue);
  const optimizedEbitda = l.estimatedRevenue * .20;
  const valueAfterOptimization = optimizedEbitda * 6;
  const estimatedPurchasePrice = l.estimatedEbitda * (l.valuationMultiple || 3.5);
  const cashRequired = (l.askingPrice || estimatedPurchasePrice) * .22;
  const debtRequired = (l.askingPrice || estimatedPurchasePrice) * .78;
  const annualDebtService = loanPayment(debtRequired, .09 / 12, 84) * 12;
  const dscr = safeDivide(optimizedEbitda, annualDebtService);
  const paybackYears = optimizedEbitda > 0 ? ((l.askingPrice || estimatedPurchasePrice) / optimizedEbitda).toFixed(1) : "NA";
  const acquisitionScore = pcpAcquisitionScore({ ...l, ebitdaMargin });
  return {
    ...l,
    ebitdaMargin,
    revenuePerPatient: safeDivide(l.estimatedRevenue, l.activePatients),
    revenuePerProvider: safeDivide(l.estimatedRevenue, l.providers),
    estimatedPurchasePrice,
    debtRequired,
    sellerNote: (l.askingPrice || 0) * .1,
    cashRequired,
    paybackYears,
    optimizedRevenue: l.estimatedRevenue * 1.15,
    optimizedEbitda,
    valueAfterOptimization,
    valueCreationMultiple: safeDivide(valueAfterOptimization, l.askingPrice || estimatedPurchasePrice),
    priyaValue: valueAfterOptimization * .5,
    raghavValue: valueAfterOptimization * .5,
    acquisitionScore,
    dscr
  };
}

function enrichTrial(t) {
  const enrollmentProgress = safeDivide(t.enrolled, t.enrollmentTarget) * 100;
  const recruitmentGap = Math.max(0, t.enrollmentTarget - t.enrolled);
  const screenFailureRate = safeDivide(t.screenFailures, t.screenFailures + t.enrolled);
  const dropoutRate = safeDivide(t.dropouts, t.enrolled);
  const revenuePerEnrolled = safeDivide(t.netProjectedRevenue, Math.max(1, t.enrollmentTarget));
  const marginPerEnrolled = revenuePerEnrolled * t.projectedMargin;
  return { ...t, enrollmentProgress, recruitmentGap, screenFailureRate, dropoutRate, revenuePerEnrolled, marginPerEnrolled, trialScore: clinicalTrialScore(t) };
}

function enrichCampaign(c) {
  const costPerLead = safeDivide(c.spend, c.leads);
  const costPerQualifiedLead = safeDivide(c.spend, c.qualifiedLeads);
  const costPerPatient = safeDivide(c.spend, c.patientsAcquired);
  const costPerTrialPatient = safeDivide(c.spend, c.trialPatientsEnrolled);
  const roas = safeDivide(c.revenueGenerated, c.spend);
  const roi = safeDivide(c.revenueGenerated - c.spend, c.spend);
  return { ...c, costPerLead, costPerQualifiedLead, costPerPatient, costPerTrialPatient, roas: Number(roas.toFixed(2)), roi };
}

function enrichMso(c) {
  const monthlyRevenue = c.grossCollections * c.msoFeePct / 12 + c.fixedMonthlyFee + c.setupFee / Math.max(1, c.contractTerm);
  const annualRevenue = monthlyRevenue * 12;
  const annualCost = c.costToServe * 12;
  const grossMargin = safeDivide(annualRevenue - annualCost, annualRevenue);
  const ebitdaContribution = annualRevenue - annualCost;
  const clientLtv = c.churnProbability ? ebitdaContribution / c.churnProbability : ebitdaContribution * 5;
  const clientCac = c.setupFee + 15000;
  const paybackMonths = ebitdaContribution > 0 ? clientCac / (ebitdaContribution / 12) : 999;
  const enterpriseValue = Math.max(annualRevenue * 2.5, ebitdaContribution * 8);
  return { ...c, monthlyRevenue, annualRevenue, grossMargin, ebitdaContribution, clientLtv, clientCac, paybackMonths: Number(paybackMonths.toFixed(1)), enterpriseValue };
}

// --- UI Helpers (pure string output) ---

function statusPill(value) {
  const text = String(value || "Unknown");
  let tone = "gray";
  if (/complete|closed|approved|scale|strong buy|buy|operating|hot/i.test(text)) tone = "green";
  if (/progress|active|selected|recruiting|screening|warm|watch|planning/i.test(text)) tone = "blue";
  if (/waiting|medium|draft|research|planned|loi|budget|negotiation/i.test(text)) tone = "amber";
  if (/blocked|critical|overdue|high|urgent|kill|pass|dead|stop|failed/i.test(text)) tone = "red";
  if (/trial|clinical|cda|irb|enrolling|startup/i.test(text)) tone = "purple";
  if (/low|not started|cold|paused/i.test(text)) tone = "gray";
  if (/mso|rcm|finance/i.test(text)) tone = "cyan";
  return `<span class="status-pill ${tone}">${escapeHtml(text)}</span>`;
}

function progressBar(value) {
  const pct = clamp(Number(value) || 0, 0, 100);
  return `<div style="display:grid;gap:5px;"><div class="progress"><span style="width:${pct}%"></span></div><span style="color:var(--muted);font-size:11px;">${pct.toFixed(0)}%</span></div>`;
}

module.exports = {
  shortMoney,
  formatPct,
  formatKpi,
  shortLabel,
  csvValue,
  formatRangeValue,
  escapeHtml,
  escapeAttr,
  daysBetween,
  todayIso,
  daysOverdue,
  sum,
  average,
  countBy,
  groupSum,
  normalize,
  safeDivide,
  clamp,
  loanPayment,
  getValue,
  taskPriorityScore,
  pcpAcquisitionScore,
  pcpStartupScore,
  clinicalTrialScore,
  trialSiteScore,
  stateCombinedScore,
  enrichPcpLead,
  enrichTrial,
  enrichCampaign,
  enrichMso,
  statusPill,
  progressBar,
};
