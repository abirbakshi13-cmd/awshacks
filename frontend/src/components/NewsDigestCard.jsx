import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { fetchDigest } from '../api';
import { COLOR_GREEN, COLOR_RED } from '../theme';

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

export default function NewsDigestCard({ selectedTicker, prices }) {
  const [digest, setDigest] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selectedTicker) {
      setDigest(null);
      return;
    }

    let ignore = false;
    setLoading(true);
    setDigest(null);

    fetchDigest(selectedTicker).then((data) => {
      if (!ignore) {
        setDigest(data);
        setLoading(false);
      }
    });

    return () => {
      ignore = true;
    };
  }, [selectedTicker]);

  const priceData = selectedTicker ? prices[selectedTicker] : null;
  const dayChange = priceData?.day_change_pct;
  const changeColor = dayChange >= 0 ? COLOR_GREEN : COLOR_RED;

  // Single root motion.div so the panel entry animation fires exactly once.
  return (
    <motion.div
      className={`panel panel-digest${!selectedTicker ? ' nd-empty' : ''}`}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: 'easeOut', delay: 0.12 }}
    >
      {!selectedTicker ? (
        'Select a stock in the graph to see its digest.'
      ) : (
        <>
          <div className="nd-header">
            <span className="nd-ticker">{selectedTicker}</span>
            {priceData ? (
              <span className="nd-price-row">
                <span className="nd-price">{usd.format(priceData.price)}</span>
                <span className="nd-change" style={{ color: changeColor }}>
                  {dayChange >= 0 ? '+' : ''}{dayChange.toFixed(2)}%
                </span>
              </span>
            ) : (
              <span className="nd-price nd-price-na">Price unavailable</span>
            )}
          </div>

          <div className="nd-body">
            {loading && <span className="nd-loading">Loading…</span>}
            <AnimatePresence mode="wait">
              {digest && (
                <motion.p
                  key={selectedTicker}
                  className="nd-summary"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.15 }}
                >
                  {digest.summary}
                </motion.p>
              )}
            </AnimatePresence>
          </div>
        </>
      )}
    </motion.div>
  );
}
