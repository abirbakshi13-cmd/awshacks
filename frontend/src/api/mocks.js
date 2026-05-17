export const USE_MOCKS = true;

const delay = (ms) => new Promise((res) => setTimeout(res, ms));

const DEFAULT_HOLDINGS = [
  { ticker: 'AAPL', shares: 50, cost_basis: 150 },
  { ticker: 'MSFT', shares: 30, cost_basis: 280 },
  { ticker: 'NVDA', shares: 20, cost_basis: 400 },
];

const DIGESTS = {
  AAPL: 'Apple continues to dominate premium consumer hardware with strong iPhone 16 cycle demand and growing Services revenue. Analysts remain bullish on Vision Pro enterprise adoption driving incremental revenue in 2026. Supply chain diversification to India is progressing ahead of schedule, reducing geopolitical risk.',
  MSFT: 'Microsoft Azure is capturing enterprise AI workloads at an accelerating pace, with Copilot integration driving seat expansion across M365. The Activision integration is outperforming initial synergy estimates. Analysts cite Azure margin expansion as the primary upside catalyst into Q3.',
  NVDA: 'NVIDIA\'s data center segment hit a new quarterly record as hyperscalers ramp Blackwell GPU orders faster than production capacity allows. Near-term risk centers on export control policy for H20 chips into China. Long-term competitive moat from CUDA ecosystem remains a significant barrier to entry for AMD and Intel.',
  GOOGL: 'Alphabet\'s Search revenue proved resilient against AI-native competitors, with Gemini integration showing early signs of query volume uplift. YouTube ad revenue accelerated on the back of connected-TV growth. Investors are watching Waymo commercialization timelines as a potential breakout catalyst.',
  AMZN: 'Amazon Web Services reaccelerated to 18% YoY growth, driven by AI infrastructure spending and data migration tailwinds. Retail operating margins reached a new high as logistics cost optimization initiatives continue. Advertising remains the highest-margin segment and is growing faster than the core retail business.',
  TSM: 'TSMC reported record advanced-node utilization as AI chip demand from NVIDIA, Apple, and AMD outpaces capacity additions. The Arizona fab is ramping N3 production, though at higher cost than Taiwan operations. Management raised full-year guidance citing structural demand from the AI compute buildout.',
  AMD: 'AMD\'s MI300X GPU is gaining traction in cloud inference workloads, with Microsoft and Meta expanding deployments. The CPU business is taking share from Intel in both server and client segments. Near-term headwind from China export restrictions is creating a 3–5% revenue drag that the street has largely priced in.',
};

const BASE_PRICES = {
  AAPL: 213.5,
  MSFT: 425.2,
  NVDA: 875.3,
  GOOGL: 178.9,
  AMZN: 192.4,
  TSM: 168.7,
  AMD: 158.2,
};

export async function fetchGraph(holdings = DEFAULT_HOLDINGS) {
  await delay(200);

  const holdingTickers = holdings.map((h) => h.ticker);

  const holdingNodes = holdings.map((h, i) => ({
    id: h.ticker,
    label: h.ticker,
    size: 18 + i * 2,
  }));

  const relatedTickers = ['GOOGL', 'AMZN', 'TSM', 'AMD'].filter(
    (t) => !holdingTickers.includes(t)
  );

  const relatedNodes = relatedTickers.map((t) => ({
    id: t,
    label: t,
    size: 9,
  }));

  const edges = [
    { from: 'AAPL', to: 'MSFT', weight: 0.72 },
    { from: 'AAPL', to: 'GOOGL', weight: 0.58 },
    { from: 'MSFT', to: 'GOOGL', weight: 0.81 },
    { from: 'MSFT', to: 'AMZN', weight: 0.65 },
    { from: 'NVDA', to: 'AAPL', weight: 0.43 },
    { from: 'NVDA', to: 'TSM', weight: 0.89 },
    { from: 'NVDA', to: 'AMD', weight: 0.76 },
    { from: 'AMD', to: 'TSM', weight: 0.84 },
    { from: 'GOOGL', to: 'AMZN', weight: 0.61 },
  ].filter(
    (e) =>
      [...holdingTickers, ...relatedTickers].includes(e.from) &&
      [...holdingTickers, ...relatedTickers].includes(e.to)
  );

  const totalValue = holdings.reduce((sum, h) => {
    const price = BASE_PRICES[h.ticker] ?? 100;
    return sum + price * h.shares;
  }, 0);

  const positions = holdings.map((h) => {
    const price = BASE_PRICES[h.ticker] ?? 100;
    const currentValue = price * h.shares;
    const costValue = h.cost_basis * h.shares;
    const pl = currentValue - costValue;
    const pl_pct = ((pl / costValue) * 100).toFixed(2);
    return { ticker: h.ticker, pl: parseFloat(pl.toFixed(2)), pl_pct: parseFloat(pl_pct) };
  });

  return {
    nodes: [...holdingNodes, ...relatedNodes],
    edges,
    portfolio: {
      value: parseFloat(totalValue.toFixed(2)),
      positions,
    },
  };
}

export async function fetchDigest(ticker) {
  await delay(200);
  const summary = DIGESTS[ticker] ?? `${ticker} is an actively traded equity with analyst coverage across multiple institutional desks. Recent price action reflects broader sector rotation and macro uncertainty. Monitor upcoming earnings for near-term catalysts.`;
  return { ticker, summary };
}

export async function sendTestAlert() {
  await delay(200);
  console.log('[mock] sendTestAlert called');
  return true;
}

export async function saveUser(userItem) {
  await delay(200);
  console.log('[mock] saveUser payload:', userItem);
  return true;
}

export async function fetchPrices(tickers) {
  await delay(150);
  const result = {};
  for (const ticker of tickers) {
    const base = BASE_PRICES[ticker] ?? 100;
    const jitter = (Math.random() - 0.5) * base * 0.02;
    const price = parseFloat((base + jitter).toFixed(2));
    const day_change_pct = parseFloat(((Math.random() - 0.48) * 4).toFixed(2));
    result[ticker] = { price, day_change_pct };
  }
  return result;
}
