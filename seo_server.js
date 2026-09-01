const fs = require("fs");
const http = require("http");
const path = require("path");
const { spawn } = require("child_process");
const {
  renderLlms,
  renderRobots,
  renderSitemap,
} = require("./public/seo-config");

const PUBLIC_PORT = Number(process.env.PORT || 5000);
const STREAMLIT_PORT = Number(process.env.STREAMLIT_PORT || 8501);
const PUBLIC_ROOT = path.join(__dirname, "public");
const PYTHON_BIN = process.env.PYTHON_BIN || "python3";
let shuttingDown = false;

const streamlit = spawn(
  PYTHON_BIN,
  ["main.py"],
  {
    stdio: "inherit",
    env: {
      ...process.env,
      STREAMLIT_PORT: String(STREAMLIT_PORT),
      STREAMLIT_ADDRESS: "127.0.0.1",
    },
  },
);

streamlit.on("error", (error) => {
  console.error(`Could not start Streamlit: ${error.message}`);
  process.exitCode = 1;
});

streamlit.on("exit", (code, signal) => {
  if (shuttingDown) return;
  console.error(`Streamlit stopped unexpectedly (code=${code}, signal=${signal})`);
  server.close(() => process.exit(code || 1));
});

function sendText(res, body, contentType, statusCode = 200) {
  const data = Buffer.from(body, "utf8");
  res.writeHead(statusCode, {
    "Content-Type": `${contentType}; charset=utf-8`,
    "Content-Length": data.length,
    "Cache-Control": "public, max-age=300",
  });
  res.end(data);
}

function sendStatic(res, filePath) {
  fs.readFile(filePath, (error, data) => {
    if (error) {
      sendText(res, "Not found\n", "text/plain", 404);
      return;
    }
    res.writeHead(200, {
      "Content-Type": "text/html; charset=utf-8",
      "Content-Length": data.length,
      "Cache-Control": "public, max-age=300",
    });
    res.end(data);
  });
}

function sendSocialPreview(res, headOnly = false) {
  fs.readFile(path.join(__dirname, "static", "og-image.svg"), (error, data) => {
    if (error) {
      sendText(res, "Not found\n", "text/plain", 404);
      return;
    }
    res.writeHead(200, {
      "Content-Type": "image/svg+xml",
      "Content-Length": data.length,
      "Cache-Control": "public, max-age=86400, immutable",
    });
    res.end(headOnly ? undefined : data);
  });
}

function upstreamPath(url) {
  if (url === "/tool" || url === "/tool/") {
    return "/";
  }
  if (url.startsWith("/tool/")) {
    return url.slice("/tool".length);
  }
  return url;
}

function webSocketOriginAllowed(req) {
  const origin = req.headers.origin;
  if (!origin) return true;
  try {
    const originUrl = new URL(origin);
    const requestHost = String(req.headers.host || "").toLowerCase();
    return (
      (originUrl.protocol === "https:" || originUrl.protocol === "http:") &&
      originUrl.host.toLowerCase() === requestHost
    );
  } catch {
    return false;
  }
}

function proxyRequest(req, res) {
  const targetPath = upstreamPath(req.url);
  const headers = { ...req.headers, host: `127.0.0.1:${STREAMLIT_PORT}` };
  const proxy = http.request(
    {
      hostname: "127.0.0.1",
      port: STREAMLIT_PORT,
      method: req.method,
      path: targetPath,
      headers,
    },
    (upstream) => {
      const responseHeaders = { ...upstream.headers };
      if (targetPath === "/") {
        responseHeaders["cache-control"] = "no-store, max-age=0";
        responseHeaders["clear-site-data"] = '"cache"';
        delete responseHeaders.etag;
        delete responseHeaders["last-modified"];
      }
      res.writeHead(upstream.statusCode || 502, responseHeaders);
      upstream.pipe(res);
    },
  );
  proxy.on("error", (error) => {
    if (!res.headersSent) {
      sendText(res, `Interactive tool unavailable: ${error.message}\n`, "text/plain", 502);
    }
  });
  req.pipe(proxy);
}

const server = http.createServer((req, res) => {
  if (req.method !== "GET" && req.method !== "HEAD") {
    proxyRequest(req, res);
    return;
  }

  const requestPath = (req.url || "/").split("?")[0];
  if (requestPath === "/robots.txt") {
    sendText(res, renderRobots(), "text/plain");
  } else if (requestPath === "/sitemap.xml") {
    sendText(res, renderSitemap(), "application/xml");
  } else if (requestPath === "/llms.txt") {
    sendText(res, renderLlms(), "text/plain");
  } else if (requestPath === "/social-preview" || requestPath === "/og-image.svg") {
    sendSocialPreview(res, req.method === "HEAD");
  } else if (requestPath === "/") {
    proxyRequest(req, res);
  } else if (requestPath === "/methodology") {
    res.writeHead(308, { Location: "/methodology/" });
    res.end();
  } else if (requestPath === "/methodology/") {
    sendStatic(res, path.join(PUBLIC_ROOT, "methodology", "index.html"));
  } else if (requestPath === "/tool" || requestPath === "/tool/") {
    res.writeHead(302, { Location: "/" });
    res.end();
  } else {
    proxyRequest(req, res);
  }
});

server.on("upgrade", (req, socket, head) => {
  socket.on("error", () => {
    socket.destroy();
  });
  if (!webSocketOriginAllowed(req)) {
    socket.end(
      "HTTP/1.1 403 Forbidden\r\n" +
      "Connection: close\r\n" +
      "Content-Type: text/plain; charset=utf-8\r\n" +
      "Content-Length: 26\r\n\r\n" +
      "WebSocket origin rejected\n",
    );
    return;
  }
  const targetPath = upstreamPath(req.url);
  const headers = { ...req.headers, host: `127.0.0.1:${STREAMLIT_PORT}` };
  // The browser's public Origin is valid at the SEO proxy, but Streamlit sees
  // this second hop as 127.0.0.1 and rejects that public Origin. The outer
  // This public proxy validated the browser Origin above, so do not forward it
  // to the private loopback WebSocket hop.
  delete headers.origin;
  const proxy = http.request(
    {
      hostname: "127.0.0.1",
      port: STREAMLIT_PORT,
      method: req.method,
      path: targetPath,
      headers,
    },
  );
  proxy.on("upgrade", (upstreamResponse, upstreamSocket, upstreamHead) => {
    upstreamSocket.on("error", () => {
      socket.destroy();
    });
    const statusLine = `HTTP/1.1 ${upstreamResponse.statusCode} ${upstreamResponse.statusMessage || ""}\r\n`;
    const responseHeaders = Object.entries(upstreamResponse.headers)
      .flatMap(([name, values]) => {
        const list = Array.isArray(values) ? values : [values];
        return list.map((value) => `${name}: ${value}\r\n`);
      })
      .join("");
    socket.write(`${statusLine}${responseHeaders}\r\n`);
    if (upstreamHead.length) socket.write(upstreamHead);
    if (head.length) upstreamSocket.write(head);
    socket.pipe(upstreamSocket).pipe(socket);
  });
  proxy.on("response", (upstreamResponse) => {
    const statusLine = `HTTP/1.1 ${upstreamResponse.statusCode || 502} ${upstreamResponse.statusMessage || ""}\r\n`;
    const responseHeaders = Object.entries(upstreamResponse.headers)
      .flatMap(([name, values]) => {
        const list = Array.isArray(values) ? values : [values];
        return list.map((value) => `${name}: ${value}\r\n`);
      })
      .join("");
    socket.write(`${statusLine}${responseHeaders}\r\n`);
    upstreamResponse.pipe(socket);
  });
  proxy.on("error", () => socket.destroy());
  proxy.end();
});

server.listen(PUBLIC_PORT, "0.0.0.0", () => {
  console.log(`SEO front server listening on port ${PUBLIC_PORT}`);
  console.log(`Streamlit tool proxied at /tool/ on port ${STREAMLIT_PORT}`);
});

function shutdown() {
  shuttingDown = true;
  streamlit.kill("SIGTERM");
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 5000).unref();
}

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);