# Runtime environment variables

Set values in Coolify's application environment. Do not commit secret values.
The server starts without optional integrations configured; only the related
feature is unavailable until its variables are supplied.

## Server

| Variable | Required | Purpose |
| --- | --- | --- |
| `PORT` | No | Public HTTP port; defaults to `5000`. The gateway listens on `0.0.0.0`. |
| `APP_ENV` | No | Set to `production` for indexable SEO responses; set to `development` for the local development identity. Docker sets `production`. |
| `PUBLIC_APP_URL` | For Google sign-in / billing return URLs | Public HTTPS origin, for example `https://soxlpro.xyz`; no path, query, or fragment. |
| `SOXL_DISABLE_WORKER` | No | Set to `1` to disable the market-refresh workers. |

## Database and visitor counter

| Variable | Required | Purpose |
| --- | --- | --- |
| `NEON_DATABASE_URL` | Recommended when using your own Neon database | Full PostgreSQL connection string. Takes priority over `DATABASE_URL` for all app database connections. |
| `DATABASE_URL` | Recommended if `NEON_DATABASE_URL` is unset | Standard PostgreSQL connection URL used for market snapshots, diagnostics, anonymous visitor counts, and Stripe event persistence. On Coolify, set either variable to your own database connection string. |
| `SESSION_SECRET` | Recommended | Signs Google-auth cookies and anonymous visitor identifiers. Use a long random value. |

## Market data

| Variable | Required | Purpose |
| --- | --- | --- |
| `EODHD_API_KEY` | Optional | EODHD historical market data. |
| `POLYGON_API_KEY` | Optional | Polygon options-chain and options-history data. |

## AI and text-quality providers

| Variable | Required | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Optional | Anthropic strategy generation and diagnostic checks. |
| `ANTHROPIC_BASE_URL` | No | Optional Anthropic-compatible API base URL. |
| `OPENAI_API_KEY` | Optional | OpenAI-powered app and diagnostic features. |
| `OPENAI_BASE_URL` | No | Optional OpenAI-compatible API base URL. |
| `R1_ANTHROPIC_MODEL` | No | Anthropic model selected by the system diagnostic; defaults to `claude-sonnet-4-5`. |
| `GPTZERO_API_KEY` | Optional | GPTZero text-quality diagnostic. |

## Google sign-in and Stripe

| Variable | Required | Purpose |
| --- | --- | --- |
| `GOOGLE_CLIENT_ID` | Optional | Google OAuth client ID. |
| `GOOGLE_CLIENT_SECRET` | Optional | Google OAuth client secret. |
| `STRIPE_SECRET_KEY` | Optional | Stripe API access for checkout and event processing. |
| `STRIPE_WEBHOOK_SECRET` | Optional | Verifies signed requests to `POST /api/stripe/webhook`. |
| `STRIPE_PRICE_ID` | Optional | Stripe price used by the legacy checkout flow. |

## Tests only

| Variable | Purpose |
| --- | --- |
| `SOXL_TEST_BASE_URL` | Base URL for live browser tests; defaults to `http://127.0.0.1:5000/`. |
| `CHROMIUM_PATH` | Optional path to a locally installed Chromium executable for live browser tests. |
| `WEBHOOK_DB_TEST` | Explicit opt-in for the webhook database integration test. |
| `PROBE_PORT` | Optional isolated port used by the cold-start probe. |
| `SESSION_TEST_PORT` | Optional port used by the chart-session browser test. |
| `PRICE_SCENARIO_TEST_PORT` | Optional port used by the price-scenario browser test. |
| `WAIT_FOR_COMPONENT_UPGRADE` | Set to `1` when the chart benchmark test should wait for a component upgrade. |
