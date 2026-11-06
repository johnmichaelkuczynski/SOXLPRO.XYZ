const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const checked = [];

function checkSource(source, filename) {
  new vm.Script(source, { filename });
  checked.push(filename);
}

function walk(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      walk(file);
    } else if (entry.isFile() && entry.name.endsWith(".js")) {
      checkSource(fs.readFileSync(file, "utf8"), path.relative(root, file));
    } else if (entry.isFile() && entry.name.endsWith(".html")) {
      const html = fs.readFileSync(file, "utf8");
      const scripts = /<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi;
      for (const match of html.matchAll(scripts)) {
        const attributes = match[1];
        if (/\bsrc\s*=/.test(attributes)) continue;
        const type = attributes.match(/\btype\s*=\s*["']([^"']+)["']/i)?.[1];
        if (type && !/(?:java|ecma)script/i.test(type)) continue;
        if (match[2].trim()) {
          checkSource(match[2], `${path.relative(root, file)} inline script`);
        }
      }
    }
  }
}

walk(path.join(root, "components"));
checkSource(
  fs.readFileSync(path.join(root, "preview_recovery.js"), "utf8"),
  "preview_recovery.js",
);
fs.writeFileSync(
  "/tmp/soxl-js-build-manifest.json",
  JSON.stringify({ checked: checked.length, files: checked }, null, 2),
);
console.log(`Validated ${checked.length} browser JavaScript sources.`);
