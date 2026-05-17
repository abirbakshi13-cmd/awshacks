import { useState, useEffect, useMemo } from 'react';
import { fetchGraph, fetchPrices } from './api';
import HoldingsEditor from './components/HoldingsEditor';
import RelationshipGraph from './components/RelationshipGraph';
import PortfolioPanel from './components/PortfolioPanel';
import NewsDigestCard from './components/NewsDigestCard';
import './App.css';

const DEFAULT_HOLDINGS = [
  { ticker: 'AAPL', shares: 50, cost_basis: 150 },
  { ticker: 'MSFT', shares: 30, cost_basis: 280 },
  { ticker: 'NVDA', shares: 20, cost_basis: 400 },
];

export default function App() {
  const [holdings, setHoldings] = useState(DEFAULT_HOLDINGS);
  const [graphData, setGraphData] = useState(null);
  const [selectedTicker, setSelectedTicker] = useState(null);
  const [prices, setPrices] = useState({});
  const [lastPriceTick, setLastPriceTick] = useState(null);
  const [phoneNumber, setPhoneNumber] = useState('');
  const [recomputing, setRecomputing] = useState(false);

  // Initial graph fetch only — graph never auto-refreshes.
  useEffect(() => {
    fetchGraph(DEFAULT_HOLDINGS).then(setGraphData);
  }, []);

  // Price refresh keyed on ticker names only. Editing shares/cost_basis does
  // not restart the interval; only adding/removing a holding does.
  const tickerKey = holdings.map((h) => h.ticker).filter(Boolean).join(',');
  useEffect(() => {
    const tickers = tickerKey ? tickerKey.split(',') : [];
    if (tickers.length === 0) return;

    function tick() {
      fetchPrices(tickers).then((data) => {
        setPrices(data);
        setLastPriceTick(Date.now());
      });
    }

    tick();
    const id = setInterval(tick, 30000);
    return () => clearInterval(id);
  }, [tickerKey]);

  // Portfolio computed from live prices — same shape as /graph portfolio response.
  // PortfolioPanel is the only consumer; it doesn't touch graphData.portfolio.
  const portfolio = useMemo(() => {
    const valid = holdings.filter((h) => h.ticker && prices[h.ticker]);
    if (valid.length === 0) return null;

    let totalValue = 0;
    const positions = valid.map((h) => {
      const price = prices[h.ticker].price;
      const shares = Number(h.shares) || 0;
      const costBasis = Number(h.cost_basis) || 0;
      const currentValue = price * shares;
      const costValue = costBasis * shares;
      const pl = currentValue - costValue;
      const pl_pct = costValue > 0 ? (pl / costValue) * 100 : 0;
      totalValue += currentValue;
      return {
        ticker: h.ticker,
        pl: parseFloat(pl.toFixed(2)),
        pl_pct: parseFloat(pl_pct.toFixed(2)),
      };
    });

    return { value: parseFloat(totalValue.toFixed(2)), positions };
  }, [holdings, prices]);

  async function handleRecompute() {
    setRecomputing(true);
    const data = await fetchGraph(holdings);
    setGraphData(data);
    setRecomputing(false);
  }

  return (
    <div className="app-layout">
      <HoldingsEditor
        holdings={holdings}
        setHoldings={setHoldings}
        phoneNumber={phoneNumber}
        setPhoneNumber={setPhoneNumber}
        onRecompute={handleRecompute}
        recomputing={recomputing}
      />

      <main className="main-area">
        <RelationshipGraph
          graphData={graphData}
          holdings={holdings}
          selectedTicker={selectedTicker}
          setSelectedTicker={setSelectedTicker}
        />
        <NewsDigestCard
          selectedTicker={selectedTicker}
          prices={prices}
        />
      </main>

      <PortfolioPanel
        portfolio={portfolio}
        lastPriceTick={lastPriceTick}
      />
    </div>
  );
}
