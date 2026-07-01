const {
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
} = require("../src/utils");

// ============================================================
// Formatting Functions
// ============================================================

describe("shortMoney", () => {
  test("formats billions", () => {
    expect(shortMoney(2500000000)).toBe("$2.5B");
    expect(shortMoney(1000000000)).toBe("$1.0B");
  });

  test("formats millions", () => {
    expect(shortMoney(5400000)).toBe("$5.4M");
    expect(shortMoney(1000000)).toBe("$1.0M");
  });

  test("formats thousands", () => {
    expect(shortMoney(75000)).toBe("$75K");
    expect(shortMoney(1500)).toBe("$2K");
  });

  test("formats small values", () => {
    expect(shortMoney(500)).toBe("$500");
    expect(shortMoney(0)).toBe("$0");
  });

  test("handles negative values", () => {
    expect(shortMoney(-3000000)).toBe("-$3.0M");
    expect(shortMoney(-50000)).toBe("-$50K");
  });

  test("handles non-numeric input", () => {
    expect(shortMoney(null)).toBe("$0");
    expect(shortMoney(undefined)).toBe("$0");
    expect(shortMoney("abc")).toBe("$0");
  });
});

describe("formatPct", () => {
  test("formats decimal fractions as percent", () => {
    expect(formatPct(0.5)).toBe("50.0%");
    expect(formatPct(0.123)).toBe("12.3%");
  });

  test("formats whole numbers > 1 as percent (divides by 100)", () => {
    expect(formatPct(50)).toBe("50.0%");
    expect(formatPct(75)).toBe("75.0%");
  });

  test("handles zero and null", () => {
    expect(formatPct(0)).toBe("0.0%");
    expect(formatPct(null)).toBe("0.0%");
  });
});

describe("formatKpi", () => {
  test("money kind uses shortMoney", () => {
    expect(formatKpi(5000000, "money")).toBe("$5.0M");
  });

  test("pct kind uses formatPct", () => {
    expect(formatKpi(0.75, "pct")).toBe("75.0%");
  });

  test("num kind formats number", () => {
    expect(formatKpi(12345, "num")).toBe("12,345");
  });

  test("unknown kind escapes HTML", () => {
    expect(formatKpi("<b>test</b>", "other")).toBe("&lt;b&gt;test&lt;/b&gt;");
  });
});

describe("shortLabel", () => {
  test("returns full text if within max", () => {
    expect(shortLabel("hello", 10)).toBe("hello");
  });

  test("truncates with dot if over max", () => {
    expect(shortLabel("hello world", 6)).toBe("hello.");
  });

  test("handles null/undefined", () => {
    expect(shortLabel(null, 5)).toBe("");
    expect(shortLabel(undefined, 5)).toBe("");
  });
});

describe("csvValue", () => {
  test("returns simple values as-is", () => {
    expect(csvValue("hello")).toBe("hello");
    expect(csvValue(42)).toBe("42");
  });

  test("quotes values with commas", () => {
    expect(csvValue("a,b")).toBe('"a,b"');
  });

  test("quotes values with newlines", () => {
    expect(csvValue("line1\nline2")).toBe('"line1\nline2"');
  });

  test("escapes double quotes", () => {
    expect(csvValue('say "hi"')).toBe('"say ""hi"""');
  });

  test("handles null/undefined", () => {
    expect(csvValue(null)).toBe("");
    expect(csvValue(undefined)).toBe("");
  });
});

describe("formatRangeValue", () => {
  test("formats money-related labels as shortMoney when >= 1000", () => {
    expect(formatRangeValue(5000, "revenue")).toBe("$5K");
    expect(formatRangeValue(2000000, "spend")).toBe("$2.0M");
  });

  test("formats percentage-related labels with %", () => {
    expect(formatRangeValue(75, "margin")).toBe("75%");
    expect(formatRangeValue(30, "rate")).toBe("30%");
  });

  test("formats plain numbers with locale formatting", () => {
    expect(formatRangeValue(12345, "count")).toBe("12,345");
  });

  test("small money values still use shortMoney format", () => {
    expect(formatRangeValue(500, "revenue")).toBe("500");
  });
});

// ============================================================
// HTML/Security Functions
// ============================================================

describe("escapeHtml", () => {
  test("escapes & < > \" '", () => {
    expect(escapeHtml('&<>"\'')).toBe("&amp;&lt;&gt;&quot;&#39;");
  });

  test("returns empty string for null/undefined", () => {
    expect(escapeHtml(null)).toBe("");
    expect(escapeHtml(undefined)).toBe("");
  });

  test("passes through safe strings", () => {
    expect(escapeHtml("hello world")).toBe("hello world");
  });
});

describe("escapeAttr", () => {
  test("escapes backticks in addition to HTML chars", () => {
    expect(escapeAttr("`test`")).toBe("&#96;test&#96;");
  });

  test("escapes all HTML special chars", () => {
    expect(escapeAttr('<a href="x">')).toBe("&lt;a href=&quot;x&quot;&gt;");
  });
});

// ============================================================
// Date Helper Functions
// ============================================================

describe("daysBetween", () => {
  test("calculates positive days between two dates", () => {
    expect(daysBetween("2024-01-01", "2024-01-10")).toBe(9);
  });

  test("returns negative for reverse order", () => {
    expect(daysBetween("2024-01-10", "2024-01-01")).toBe(-9);
  });

  test("returns 0 for same date", () => {
    expect(daysBetween("2024-06-15", "2024-06-15")).toBe(0);
  });
});

describe("todayIso", () => {
  test("returns ISO date string in YYYY-MM-DD format", () => {
    const result = todayIso();
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe("daysOverdue", () => {
  test("returns 0 for no due date", () => {
    expect(daysOverdue(null, "In Progress")).toBe(0);
    expect(daysOverdue("", "In Progress")).toBe(0);
  });

  test("returns 0 for completed tasks", () => {
    expect(daysOverdue("2020-01-01", "Complete")).toBe(0);
    expect(daysOverdue("2020-01-01", "Cancelled")).toBe(0);
  });

  test("returns positive days for overdue items", () => {
    const pastDate = "2020-01-01";
    expect(daysOverdue(pastDate, "In Progress")).toBeGreaterThan(0);
  });

  test("returns 0 for future due dates", () => {
    expect(daysOverdue("2099-01-01", "In Progress")).toBe(0);
  });
});

// ============================================================
// Math/Data Helper Functions
// ============================================================

describe("sum", () => {
  test("sums values by string key", () => {
    const rows = [{ amount: 10 }, { amount: 20 }, { amount: 30 }];
    expect(sum(rows, "amount")).toBe(60);
  });

  test("sums values using function key", () => {
    const rows = [{ a: 2, b: 3 }, { a: 4, b: 5 }];
    expect(sum(rows, r => r.a * r.b)).toBe(26);
  });

  test("returns 0 for empty array", () => {
    expect(sum([], "x")).toBe(0);
  });

  test("handles missing keys gracefully", () => {
    const rows = [{ a: 10 }, { b: 20 }];
    expect(sum(rows, "a")).toBe(10);
  });
});

describe("average", () => {
  test("calculates average of values", () => {
    const rows = [{ v: 10 }, { v: 20 }, { v: 30 }];
    expect(average(rows, "v")).toBe(20);
  });

  test("returns 0 for empty array", () => {
    expect(average([], "v")).toBe(0);
  });
});

describe("countBy", () => {
  test("counts occurrences by key", () => {
    const rows = [
      { status: "Active" },
      { status: "Active" },
      { status: "Closed" },
    ];
    expect(countBy(rows, "status")).toEqual({ Active: 2, Closed: 1 });
  });

  test("uses 'Unknown' for missing keys", () => {
    const rows = [{ status: "A" }, {}];
    expect(countBy(rows, "status")).toEqual({ A: 1, Unknown: 1 });
  });
});

describe("groupSum", () => {
  test("groups and sums values", () => {
    const rows = [
      { region: "East", revenue: 100 },
      { region: "West", revenue: 200 },
      { region: "East", revenue: 150 },
    ];
    expect(groupSum(rows, "region", "revenue")).toEqual({ East: 250, West: 200 });
  });

  test("uses 'Unknown' for missing group key", () => {
    const rows = [{ revenue: 50 }];
    expect(groupSum(rows, "region", "revenue")).toEqual({ Unknown: 50 });
  });
});

describe("normalize", () => {
  test("returns 0 at min", () => {
    expect(normalize(10, 10, 100)).toBe(0);
  });

  test("returns 1 at max", () => {
    expect(normalize(100, 10, 100)).toBe(1);
  });

  test("returns 0.5 at midpoint", () => {
    expect(normalize(55, 10, 100)).toBeCloseTo(0.5);
  });

  test("clamps below min to 0", () => {
    expect(normalize(0, 10, 100)).toBe(0);
  });

  test("clamps above max to 1", () => {
    expect(normalize(200, 10, 100)).toBe(1);
  });
});

describe("safeDivide", () => {
  test("divides normally", () => {
    expect(safeDivide(10, 2)).toBe(5);
  });

  test("returns 0 for zero divisor", () => {
    expect(safeDivide(10, 0)).toBe(0);
  });

  test("handles null/undefined numerator", () => {
    expect(safeDivide(null, 5)).toBe(0);
    expect(safeDivide(undefined, 5)).toBe(0);
  });
});

describe("clamp", () => {
  test("returns value when in range", () => {
    expect(clamp(5, 0, 10)).toBe(5);
  });

  test("clamps to min", () => {
    expect(clamp(-5, 0, 10)).toBe(0);
  });

  test("clamps to max", () => {
    expect(clamp(15, 0, 10)).toBe(10);
  });
});

describe("loanPayment", () => {
  test("returns 0 for no principal", () => {
    expect(loanPayment(0, 0.01, 60)).toBe(0);
  });

  test("returns 0 for no months", () => {
    expect(loanPayment(100000, 0.01, 0)).toBe(0);
  });

  test("calculates simple division when rate is 0", () => {
    expect(loanPayment(12000, 0, 12)).toBe(1000);
  });

  test("calculates amortized payment with interest", () => {
    const payment = loanPayment(100000, 0.005, 360);
    expect(payment).toBeCloseTo(599.55, 1);
  });
});

describe("getValue", () => {
  test("returns value by string key", () => {
    expect(getValue({ name: "test" }, "name")).toBe("test");
  });

  test("returns value by function key", () => {
    expect(getValue({ a: 2, b: 3 }, r => r.a + r.b)).toBe(5);
  });
});

// ============================================================
// Business Logic / Scoring Functions
// ============================================================

describe("taskPriorityScore", () => {
  test("scores a critical blocked task high", () => {
    const task = { priority: "Critical", status: "Blocked", dueDate: null, financialImpact: 0, dependencyImportance: 0 };
    expect(taskPriorityScore(task)).toBe(50);
  });

  test("scores a low priority task without urgency low", () => {
    const task = { priority: "Low", status: "In Progress", dueDate: null, financialImpact: 0, dependencyImportance: 0 };
    expect(taskPriorityScore(task)).toBe(8);
  });

  test("includes financial impact in score", () => {
    const task = { priority: "Medium", status: "In Progress", dueDate: null, financialImpact: 700000, dependencyImportance: 0 };
    expect(taskPriorityScore(task)).toBe(38);
  });

  test("includes waiting status penalty", () => {
    const task = { priority: "Medium", status: "Waiting", dueDate: null, financialImpact: 0, dependencyImportance: 0 };
    expect(taskPriorityScore(task)).toBe(24);
  });

  test("caps at 100", () => {
    const task = { priority: "Critical", status: "Blocked", dueDate: "2020-01-01", financialImpact: 5000000, dependencyImportance: 20 };
    expect(taskPriorityScore(task)).toBe(100);
  });
});

describe("pcpAcquisitionScore", () => {
  test("scores a strong lead high", () => {
    const lead = {
      ebitdaMargin: 0.22,
      estimatedRevenue: 5000000,
      medicarePct: 0.55,
      ownerMotivation: 8,
      successionIssue: 9,
      valuationMultiple: 3.5,
      strategicFit: 85,
      financialFit: 80,
      clinicalFit: 75,
      dataQuality: 90,
    };
    const score = pcpAcquisitionScore(lead);
    expect(score).toBeGreaterThan(70);
    expect(score).toBeLessThanOrEqual(100);
  });

  test("scores a weak lead low", () => {
    const lead = {
      ebitdaMargin: 0.06,
      estimatedRevenue: 1200000,
      medicarePct: 0.28,
      ownerMotivation: 2,
      successionIssue: 2,
      valuationMultiple: 6.5,
      strategicFit: 45,
      financialFit: 35,
      clinicalFit: 42,
      dataQuality: 25,
    };
    const score = pcpAcquisitionScore(lead);
    expect(score).toBeLessThan(30);
  });

  test("returns score between 0 and 100", () => {
    const lead = {
      ebitdaMargin: 0.15,
      estimatedRevenue: 3000000,
      medicarePct: 0.40,
      ownerMotivation: 5,
      successionIssue: 5,
      valuationMultiple: 5,
      strategicFit: 70,
      financialFit: 60,
      clinicalFit: 60,
      dataQuality: 50,
    };
    const score = pcpAcquisitionScore(lead);
    expect(score).toBeGreaterThanOrEqual(0);
    expect(score).toBeLessThanOrEqual(100);
  });
});

describe("pcpStartupScore", () => {
  test("scores a high-opportunity market well", () => {
    const market = {
      medicareLives: 18000,
      population: 75000,
      competingPcps: 25,
      urgentCares: 3,
      rent: 9000,
      ancillaryAdoption: 0.35,
      credentialingMonths: 4.5,
      hospitals: 4,
      newPatientsPerMonth: 120,
    };
    const score = pcpStartupScore(market);
    expect(score).toBeGreaterThan(60);
  });

  test("scores a saturated market low", () => {
    const market = {
      medicareLives: 5000,
      population: 50000,
      competingPcps: 100,
      urgentCares: 20,
      rent: 20000,
      ancillaryAdoption: 0.15,
      credentialingMonths: 7,
      hospitals: 1,
      newPatientsPerMonth: 55,
    };
    const score = pcpStartupScore(market);
    expect(score).toBeLessThan(30);
  });
});

describe("clinicalTrialScore", () => {
  test("scores an active high-margin trial well", () => {
    const trial = {
      enrolled: 80,
      enrollmentTarget: 100,
      projectedMargin: 0.35,
      netProjectedRevenue: 450000,
      stage: "Active",
      screenFailures: 5,
    };
    const score = clinicalTrialScore(trial);
    expect(score).toBeGreaterThan(70);
  });

  test("scores an early low-revenue trial lower", () => {
    const trial = {
      enrolled: 10,
      enrollmentTarget: 80,
      projectedMargin: 0.18,
      netProjectedRevenue: 180000,
      stage: "Lead",
      screenFailures: 3,
    };
    const score = clinicalTrialScore(trial);
    expect(score).toBeLessThan(50);
  });
});

describe("trialSiteScore", () => {
  test("scores a strong site highly", () => {
    const site = {
      patientDatabase: 45000,
      piCount: 6,
      coordinatorCount: 8,
      activeStudies: 10,
      ebitda: 350000,
      annualRevenue: 1200000,
      qualityScore: 88,
      croRelationships: 80,
    };
    const score = trialSiteScore(site);
    expect(score).toBeGreaterThan(65);
  });

  test("scores a weak site low", () => {
    const site = {
      patientDatabase: 8000,
      piCount: 1,
      coordinatorCount: 2,
      activeStudies: 2,
      ebitda: 50000,
      annualRevenue: 500000,
      qualityScore: 55,
      croRelationships: 45,
    };
    const score = trialSiteScore(site);
    expect(score).toBeLessThan(30);
  });
});

describe("stateCombinedScore", () => {
  test("returns 0 for null input", () => {
    expect(stateCombinedScore(null)).toBe(0);
  });

  test("calculates weighted average minus risk penalty", () => {
    const state = {
      pcpOpportunityScore: 80,
      trialsOpportunityScore: 70,
      medicareOpportunity: 75,
      ruralOpportunity: 60,
      trialRecruitmentPotential: 65,
      cpomRisk: "Low",
      licensingComplexity: "Low",
    };
    const score = stateCombinedScore(state);
    expect(score).toBeGreaterThan(55);
    expect(score).toBeLessThanOrEqual(100);
  });

  test("applies high risk penalty", () => {
    const state = {
      pcpOpportunityScore: 80,
      trialsOpportunityScore: 70,
      medicareOpportunity: 75,
      ruralOpportunity: 60,
      trialRecruitmentPotential: 65,
      cpomRisk: "High",
      licensingComplexity: "High",
    };
    const lowRisk = stateCombinedScore({ ...state, cpomRisk: "Low", licensingComplexity: "Low" });
    const highRisk = stateCombinedScore(state);
    expect(highRisk).toBeLessThan(lowRisk);
  });
});

// ============================================================
// Enrichment Functions
// ============================================================

describe("enrichPcpLead", () => {
  const baseLead = {
    practiceName: "Test Practice",
    estimatedRevenue: 3000000,
    estimatedEbitda: 450000,
    activePatients: 2000,
    providers: 3,
    askingPrice: 1500000,
    valuationMultiple: 3.5,
    medicarePct: 0.45,
    ownerMotivation: 7,
    successionIssue: 6,
    strategicFit: 75,
    financialFit: 70,
    clinicalFit: 65,
    dataQuality: 80,
  };

  test("calculates EBITDA margin", () => {
    const enriched = enrichPcpLead(baseLead);
    expect(enriched.ebitdaMargin).toBeCloseTo(0.15);
  });

  test("calculates optimized metrics", () => {
    const enriched = enrichPcpLead(baseLead);
    expect(enriched.optimizedEbitda).toBe(600000);
    expect(enriched.optimizedRevenue).toBeCloseTo(3450000);
  });

  test("calculates debt/equity split", () => {
    const enriched = enrichPcpLead(baseLead);
    expect(enriched.cashRequired).toBe(330000);
    expect(enriched.debtRequired).toBe(1170000);
  });

  test("includes acquisition score", () => {
    const enriched = enrichPcpLead(baseLead);
    expect(enriched.acquisitionScore).toBeGreaterThan(0);
    expect(enriched.acquisitionScore).toBeLessThanOrEqual(100);
  });

  test("calculates DSCR", () => {
    const enriched = enrichPcpLead(baseLead);
    expect(enriched.dscr).toBeGreaterThan(0);
  });
});

describe("enrichTrial", () => {
  test("calculates enrollment progress and gaps", () => {
    const trial = {
      enrolled: 40,
      enrollmentTarget: 80,
      screenFailures: 10,
      dropouts: 2,
      netProjectedRevenue: 400000,
      projectedMargin: 0.3,
      stage: "Active",
    };
    const enriched = enrichTrial(trial);
    expect(enriched.enrollmentProgress).toBe(50);
    expect(enriched.recruitmentGap).toBe(40);
    expect(enriched.screenFailureRate).toBeCloseTo(0.2);
    expect(enriched.dropoutRate).toBeCloseTo(0.05);
    expect(enriched.trialScore).toBeGreaterThan(0);
  });
});

describe("enrichCampaign", () => {
  test("calculates cost per metrics and ROAS", () => {
    const campaign = {
      spend: 10000,
      leads: 200,
      qualifiedLeads: 50,
      patientsAcquired: 10,
      trialPatientsEnrolled: 5,
      revenueGenerated: 30000,
    };
    const enriched = enrichCampaign(campaign);
    expect(enriched.costPerLead).toBe(50);
    expect(enriched.costPerQualifiedLead).toBe(200);
    expect(enriched.costPerPatient).toBe(1000);
    expect(enriched.costPerTrialPatient).toBe(2000);
    expect(enriched.roas).toBe(3);
    expect(enriched.roi).toBe(2);
  });
});

describe("enrichMso", () => {
  test("calculates revenue and margin metrics", () => {
    const client = {
      grossCollections: 2400000,
      msoFeePct: 0.06,
      fixedMonthlyFee: 3000,
      setupFee: 25000,
      contractTerm: 36,
      costToServe: 5000,
      churnProbability: 0.1,
    };
    const enriched = enrichMso(client);
    expect(enriched.monthlyRevenue).toBeGreaterThan(0);
    expect(enriched.annualRevenue).toBe(enriched.monthlyRevenue * 12);
    expect(enriched.grossMargin).toBeGreaterThan(0);
    expect(enriched.grossMargin).toBeLessThan(1);
    expect(enriched.ebitdaContribution).toBeGreaterThan(0);
    expect(enriched.clientLtv).toBeGreaterThan(0);
    expect(enriched.clientCac).toBe(40000);
  });

  test("handles zero churn probability", () => {
    const client = {
      grossCollections: 1000000,
      msoFeePct: 0.05,
      fixedMonthlyFee: 2000,
      setupFee: 15000,
      contractTerm: 24,
      costToServe: 3000,
      churnProbability: 0,
    };
    const enriched = enrichMso(client);
    expect(enriched.clientLtv).toBe(enriched.ebitdaContribution * 5);
  });
});

// ============================================================
// UI Helper Functions
// ============================================================

describe("statusPill", () => {
  test("renders green for completed statuses", () => {
    expect(statusPill("Complete")).toContain("green");
    expect(statusPill("Approved")).toContain("green");
  });

  test("renders blue for active statuses", () => {
    expect(statusPill("In Progress")).toContain("blue");
    expect(statusPill("Active")).toContain("blue");
  });

  test("renders amber for waiting statuses", () => {
    expect(statusPill("Waiting")).toContain("amber");
    expect(statusPill("Draft")).toContain("amber");
  });

  test("renders red for critical statuses", () => {
    expect(statusPill("Blocked")).toContain("red");
    expect(statusPill("Critical")).toContain("red");
  });

  test("renders purple for trial statuses", () => {
    expect(statusPill("Clinical")).toContain("purple");
    expect(statusPill("Enrolling")).toContain("purple");
  });

  test("renders gray for low/paused statuses", () => {
    expect(statusPill("Paused")).toContain("gray");
    expect(statusPill("Not Started")).toContain("gray");
  });

  test("renders cyan for MSO/finance", () => {
    expect(statusPill("MSO")).toContain("cyan");
    expect(statusPill("Finance")).toContain("cyan");
  });

  test("handles null/undefined", () => {
    expect(statusPill(null)).toContain("Unknown");
    expect(statusPill(undefined)).toContain("Unknown");
  });

  test("escapes HTML in value", () => {
    expect(statusPill("<script>")).toContain("&lt;script&gt;");
  });
});

describe("progressBar", () => {
  test("renders 0% for zero", () => {
    const html = progressBar(0);
    expect(html).toContain("width:0%");
    expect(html).toContain("0%");
  });

  test("renders correct percentage", () => {
    const html = progressBar(75);
    expect(html).toContain("width:75%");
    expect(html).toContain("75%");
  });

  test("clamps values over 100", () => {
    const html = progressBar(150);
    expect(html).toContain("width:100%");
  });

  test("clamps negative values to 0", () => {
    const html = progressBar(-10);
    expect(html).toContain("width:0%");
  });
});
