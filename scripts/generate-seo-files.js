const fs = require("fs");
const path = require("path");
const {
  renderLlms,
  renderRobots,
  renderSitemap,
} = require("../public/seo-config");

const root = path.join(__dirname, "..", "public");
fs.writeFileSync(path.join(root, "robots.txt"), renderRobots());
fs.writeFileSync(path.join(root, "sitemap.xml"), renderSitemap());
fs.writeFileSync(path.join(root, "llms.txt"), renderLlms());