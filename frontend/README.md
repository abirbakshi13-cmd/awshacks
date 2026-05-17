# MIA — Market Intelligence Agent

A real-time portfolio intelligence dashboard built for the Amazon Bedrock hackathon. Enter your stock holdings and MIA visualises the relationship graph between your positions and related equities, tracks live P&L, and surfaces AI-generated market digests on demand. SMS alerts are dispatched by a scheduled Bedrock agent running in the background.

## Development

```bash
npm install
npm run dev        # starts at http://localhost:5173
```

Mock data is enabled by default — the app runs fully offline with no backend required.

## Environment variables

Copy `.env.example` to `.env.local` and fill in values:

| Variable | Default | Description |
|---|---|---|
| `VITE_API_BASE_URL` | *(empty)* | API Gateway base URL, e.g. `https://abc123.execute-api.us-east-1.amazonaws.com/prod` |
| `VITE_USE_MOCKS` | `true` | Set to `"false"` to route API calls to `VITE_API_BASE_URL` instead of mocks |

To switch to the real backend once it's deployed:

```bash
# .env.local
VITE_API_BASE_URL=https://your-api-gateway-url.execute-api.us-east-1.amazonaws.com/prod
VITE_USE_MOCKS=false
```

## Build

```bash
npm run build      # outputs to dist/
```

The `dist/` folder is what Vercel deploys. Set the environment variables in the Vercel project dashboard under Settings → Environment Variables.
