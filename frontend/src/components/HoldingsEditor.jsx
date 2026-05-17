import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { saveUser } from '../api';

const isValidPhone = (val) => /^\+\d{7,15}$/.test(val);

const ENTRY = { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.2, ease: 'easeOut', delay: 0 } };

export default function HoldingsEditor({
  holdings,
  setHoldings,
  phoneNumber,
  setPhoneNumber,
  onRecompute,
  recomputing,
}) {
  const [saved, setSaved] = useState(false);

  function handleChange(i, field, value) {
    setHoldings((prev) =>
      prev.map((h, idx) => (idx === i ? { ...h, [field]: value } : h))
    );
  }

  function handleTickerBlur(i, value) {
    handleChange(i, 'ticker', value.toUpperCase().trim());
  }

  function handleRemove(i) {
    setHoldings((prev) => prev.filter((_, idx) => idx !== i));
  }

  function handleAdd() {
    setHoldings((prev) => [...prev, { ticker: '', shares: '', cost_basis: '' }]);
  }

  async function handleSave() {
    await saveUser({
      phone_number: phoneNumber,
      holdings,
      last_prices: {},
      last_alert_ts: null,
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  const phoneInvalid = phoneNumber !== '' && !isValidPhone(phoneNumber);

  return (
    <motion.aside className="panel panel-left" {...ENTRY}>
      <div className="he-section-title">Holdings</div>

      <div className="he-col-labels">
        <span className="he-col-ticker">Ticker</span>
        <span className="he-col-shares">Shares</span>
        <span className="he-col-cost">Cost ($)</span>
      </div>

      <div className="he-rows">
        {holdings.map((h, i) => (
          <div key={i} className="he-row">
            <input
              className="he-input he-ticker"
              value={h.ticker}
              onChange={(e) => handleChange(i, 'ticker', e.target.value)}
              onBlur={(e) => handleTickerBlur(i, e.target.value)}
              placeholder="AAPL"
              maxLength={5}
            />
            <input
              className="he-input he-shares"
              type="number"
              value={h.shares}
              onChange={(e) => handleChange(i, 'shares', e.target.value)}
              placeholder="0"
              min={0}
            />
            <input
              className="he-input he-cost"
              type="number"
              value={h.cost_basis}
              onChange={(e) => handleChange(i, 'cost_basis', e.target.value)}
              placeholder="0.00"
              min={0}
              step={0.01}
            />
            <button
              className="he-remove"
              onClick={() => handleRemove(i)}
              title="Remove holding"
            >
              ×
            </button>
          </div>
        ))}
      </div>

      <button className="he-add-btn" onClick={handleAdd}>
        + Add holding
      </button>

      <div className="he-divider" />

      <div className="he-section-title">Alert phone</div>
      <input
        className={`he-input he-phone${phoneInvalid ? ' he-phone-invalid' : ''}`}
        value={phoneNumber}
        onChange={(e) => setPhoneNumber(e.target.value)}
        placeholder="+12065551234"
      />

      <div className="he-actions">
        <div className="he-save-row">
          <button className="btn-primary" onClick={handleSave}>
            Save
          </button>
          <AnimatePresence>
            {saved && (
              <motion.span
                className="he-saved-confirm"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              >
                Saved ✓
              </motion.span>
            )}
          </AnimatePresence>
        </div>
        <button
          className="btn-secondary"
          onClick={onRecompute}
          disabled={recomputing}
        >
          {recomputing ? 'Recomputing…' : 'Recompute graph'}
        </button>
      </div>
    </motion.aside>
  );
}
