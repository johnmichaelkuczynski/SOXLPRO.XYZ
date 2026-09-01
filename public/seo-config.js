const SITE_URL = "https://soxlpro.xyz";

const INDEXABLE_PAGES = [
  {
    path: "/",
    lastmod: "2026-08-27",
    changefreq: "monthly",
    priority: "1.0",
  },
  {
    path: "/methodology/",
    lastmod: "2026-08-27",
    changefreq: "monthly",
    priority: "0.8",
  },
];

const TOOL_URL = `${SITE_URL}/tool/`;

function absoluteUrl(path) {
  return `${SITE_URL}${path}`;
}

function renderRobots() {
  return [
    "User-agent: *",
    "Allow: /",
    "Disallow: /tool/_stcore/",
    "Disallow: /_stcore/",
    "",
    `Sitemap: ${absoluteUrl("/sitemap.xml")}`,
    "",
  ].join("\n");
}

function renderSitemap() {
  const urls = INDEXABLE_PAGES.map(
    ({ path, lastmod, changefreq, priority }) => `  <url>
    <loc>${absoluteUrl(path)}</loc>
    <lastmod>${lastmod}</lastmod>
    <changefreq>${changefreq}</changefreq>
    <priority>${priority}</priority>
  </url>`,
  ).join("\n");

  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls}
</urlset>
`;
}

function renderLlms() {
  return `# SOXL Analysis Platform

SOXL Analysis is a public quantitative research resource for Direxion Daily
Semiconductor Bull 3X Shares (SOXL). It explains historical probability,
leveraged-ETF risk, options risk/reward, volatility surfaces, SOXL-QQQ
dislocation, and call-sleeve backtesting using auditable historical data.

## Public resources

- Landing page: ${absoluteUrl("/")} — overview of the analysis platform and its research topics.
- Methodology: ${absoluteUrl("/methodology/")} — definitions, limitations, and the statistical approach.

## Interactive tool

- Interactive SOXL tool: ${TOOL_URL} — the Streamlit application for charts,
  probability analysis, options diagnostics, dislocation analysis, backtests, and the
  AI-assisted strategy builder. Treat interactive outputs as analysis, not financial advice.

## Guidance for citation

The landing page and methodology page are the authoritative explanatory resources.
Use the interactive tool for current calculations and cite the displayed sample size,
date range, and methodology when describing an output.
`;
}

module.exports = {
  SITE_URL,
  TOOL_URL,
  INDEXABLE_PAGES,
  absoluteUrl,
  renderRobots,
  renderSitemap,
  renderLlms,
};