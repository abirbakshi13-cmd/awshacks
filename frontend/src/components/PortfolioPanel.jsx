import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { sendTestAlert } from '../api';
import { COLOR_GREEN, COLOR_RED } from '../theme';

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

export default function PortfolioPanel({ portfolio, lastPriceTick }) {
  const [secsAgo, setSecsAgo] = useState(0);
  const [alertSent, setAlertSent] = useState(false);

  useEffect(() => {
    if (!lastPriceTick) return;
    setSecsAgo(0);
    const id = setInterval(() => {
      setSecsAgo(Math.round((Date.now() - lastPriceTick) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [lastPriceTick]);

  async function handleTestAlert() {
    await sendTestAlert();
    setAlertSent(true);
    setTimeout(() => setAlertSent(false), 2000);
  }

  return (
    <motion.aside
      className="panel panel-right"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: 'easeOut', delay: 0.18 }}
    >
      <div className="pp-header">
        <span className="pp-title">Portfolio</span>
        {portfolio && (
          <span className="pp-total">{usd.format(portfolio.value)}</span>
        )}
      </div>

      <div className="pp-positions">
        {portfolio ? (
          portfolio.positions.map((pos) => {
            const positive = pos.pl >= 0;
            const color = positive ? COLOR_GREEN : COLOR_RED;
            return (
              <div key={pos.ticker} className="pp-row">
                <span className="pp-ticker">{pos.ticker}</span>
                <span className="pp-pl" style={{ color }}>
                  {usd.format(pos.pl)}
                </span>
                <span className="pp-pct" style={{ color }}>
                  ({positive ? '+' : ''}{pos.pl_pct.toFixed(2)}%)
                </span>
              </div>
            );
          })
        ) : (
          <div className="pp-empty">Waiting for prices…</div>
        )}
      </div>

      <div className="pp-footer">
        {lastPriceTick && (
          <span className="pp-timestamp">Updated {secsAgo}s ago</span>
        )}
        <div className="pp-alert-row">
          <button className="btn-secondary pp-alert-btn" onClick={handleTestAlert}>
            Send test alert
          </button>
          <AnimatePresence>
            {alertSent && (
              <motion.span
                className="pp-alert-confirm"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              >
                Alert sent ✓
              </motion.span>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.aside>
  );
}
