import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import './App.css';
import axios from 'axios';
import { QueryClient, QueryClientProvider, useQuery } from 'react-query';
import config from './config';
import theme from './theme';
import { ThemeProvider, CssBaseline } from '@mui/material';
import {
  LineChart,
  Line,
  Area,
  ComposedChart,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';

const API_BASE_URL = config.apiUrl;
const SYMBOLS = ['BTC/USDT', 'ETH/USDT'];
const REFRESH_INTERVAL = 2000;
const MAX_HISTORY_POINTS = 300;
const MAX_ACTIVITY_ROWS = 20;
const CHART_ANIMATION = { isAnimationActive: true, animationDuration: 400 };

const FEE_TIER_LABELS = {
  retail:         'Retail (VIP 0)',
  retail_bnb:     'Retail + BNB Discount',
  vip3:           'VIP 3 (~$20M/mo)',
  vip5:           'VIP 5 (~$150M/mo)',
  vip9:           'VIP 9 (~$5B/mo)',
  market_maker:   'Registered Market Maker',
  dekabank_proxy: 'DekaBank-scale Proxy',
  zero_fee:       'Zero Fee (illustrative)',
};

const api = {
  getMarketData: async (symbol) => {
    try {
      const { data } = await axios.get(
        `${API_BASE_URL}/api/v1/market_data/${encodeURIComponent(symbol)}`,
        { timeout: 10000, headers: { Accept: 'application/json' } }
      );
      return data;
    } catch {
      return null;
    }
  },
  getSimulationStatus: async () => {
    try {
      const { data } = await axios.get(`${API_BASE_URL}/api/v1/simulation/status`, {
        timeout: 10000,
        headers: { Accept: 'application/json' },
      });
      return data;
    } catch {
      return null;
    }
  },
  getRecentTrades: async (limit = 20) => {
    try {
      const { data } = await axios.get(
        `${API_BASE_URL}/api/v1/simulation/trades?limit=${limit}`,
        { timeout: 10000, headers: { Accept: 'application/json' } }
      );
      return data.trades || [];
    } catch {
      return [];
    }
  },
  getConfig: async () => {
    try {
      const { data } = await axios.get(`${API_BASE_URL}/api/v1/config`, {
        timeout: 8000, headers: { Accept: 'application/json' },
      });
      return data;
    } catch {
      return null;
    }
  },
  updateConfig: async (payload) => {
    const { data } = await axios.post(`${API_BASE_URL}/api/v1/config`, payload, {
      timeout: 8000, headers: { 'Content-Type': 'application/json' },
    });
    return data;
  },
  runBacktest: async (payload) => {
    const { data } = await axios.post(`${API_BASE_URL}/api/v1/backtest/run`, payload, {
      timeout: 120000, headers: { 'Content-Type': 'application/json' },
    });
    return data;
  },
};

const queryClient = new QueryClient();

function formatTime(date) {
  return date.toLocaleTimeString('en-US', { hour12: false });
}

function formatChartTime(ts) {
  const d = ts instanceof Date ? ts : new Date(ts);
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

function getSignalClass(strength, threshold) {
  const s = strength ?? 0;
  const t = threshold ?? 1;
  if (s >= t) return 'negative';
  if (s >= t * 0.75) return 'warning';
  return 'positive';
}

function formatMetric(value, decimals = 4) {
  if (value == null || Number.isNaN(value)) return '—';
  return value.toFixed(decimals);
}

function formatPercent(value) {
  if (value == null || Number.isNaN(value)) return '—';
  return `${(value * 100).toFixed(2)}%`;
}

function formatUsd(value, decimals = 4) {
  if (value == null || Number.isNaN(value)) return '—';
  return value.toFixed(decimals);
}

function getRelativePriceClass(exchangeDelta, otherDelta) {
  if (exchangeDelta > otherDelta) return 'positive';
  if (exchangeDelta < otherDelta) return 'negative';
  return 'neutral';
}

function tradeSide(trade) {
  return trade.buy_exchange === 'binance' ? 'BUY' : 'SELL';
}

function exportActivityCsv(rows) {
  const header = 'Timestamp,Side,Route,Gross,Fees,Net PnL\n';
  const body = rows
    .map((r) => `${r.timestamp},${r.side},${r.route},${r.gross},${r.fees},${r.net}`)
    .join('\n');
  const blob = new Blob([header + body], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `activity_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

const tooltipStyle = {
  background: '#FFFFFF',
  border: '1px solid #DEE2E6',
  borderRadius: '6px',
  boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
  fontSize: 12,
};

function PnlTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="pnl-tooltip" style={tooltipStyle}>
      <div style={{ marginBottom: 4, fontWeight: 600 }}>Trade #{label}</div>
      {payload.map((entry) => (
        <div key={entry.dataKey} style={{ color: entry.color, fontSize: 12 }}>
          {entry.name}: {Number(entry.value).toFixed(6)}
        </div>
      ))}
    </div>
  );
}

function SpreadTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const pct = payload.find((p) => p.dataKey === 'spreadPct');
  const abs = payload.find((p) => p.dataKey === 'spreadAbs');
  return (
    <div className="pnl-tooltip" style={tooltipStyle}>
      <div style={{ marginBottom: 4, fontWeight: 600, color: '#6C757D', fontSize: 11 }}>{label}</div>
      {pct  && <div style={{ color: pct.color,  fontSize: 12 }}>Spread %: {Number(pct.value).toFixed(4)}%</div>}
      {abs  && <div style={{ color: '#adb5bd', fontSize: 12 }}>Spread $: {Number(abs.value).toFixed(4)}</div>}
    </div>
  );
}

function AppContent() {
  const [selectedSymbol, setSelectedSymbol] = useState(SYMBOLS[0]);
  const [isRunning, setIsRunning] = useState(true);
  const [currentTime, setCurrentTime] = useState(new Date());
  const [history, setHistory] = useState([]);
  const [priceTrend, setPriceTrend] = useState({ binance: '', kraken: '' });
  const prevPricesRef = useRef({ binance: null, kraken: null });

  // Tab navigation
  const [activeTab, setActiveTab] = useState('live');

  // Strategy configuration state
  const [configDraft, setConfigDraft] = useState({ feeTier: 'retail', capitalPerLeg: '1000' });
  const [configApplied, setConfigApplied] = useState(null);
  const [configSaving, setConfigSaving] = useState(false);
  const [configError, setConfigError] = useState(null);

  // Backtesting state
  const [btDraft, setBtDraft] = useState({ feeTier: 'retail', tradeAmount: '0.001', symbols: 'BTC/USDT,ETH/USDT' });
  const [btStatus, setBtStatus] = useState('idle'); // idle | running | done | error
  const [btResult, setBtResult] = useState(null);
  const [btError, setBtError]   = useState(null);

  const pollInterval = isRunning ? REFRESH_INTERVAL : false;

  const { data: marketData, error: marketDataError, isLoading: marketDataLoading, isFetching } = useQuery(
    ['marketData', selectedSymbol],
    () => api.getMarketData(selectedSymbol),
    { refetchInterval: pollInterval, retry: 1 }
  );

  const { data: simulationStatus, isLoading: simStatusLoading } = useQuery(
    'simulationStatus',
    api.getSimulationStatus,
    { refetchInterval: pollInterval, retry: 1 }
  );

  const { data: recentTrades, isLoading: tradesLoading } = useQuery(
    'recentTrades',
    () => api.getRecentTrades(MAX_ACTIVITY_ROWS),
    { refetchInterval: pollInterval, retry: 1 }
  );

  useQuery('liveConfig', api.getConfig, {
    refetchInterval: 10000, retry: 1,
    onSuccess: (d) => {
      if (d && !configApplied) {
        setConfigDraft({ feeTier: d.fee_tier, capitalPerLeg: String(d.capital_per_leg_usdt) });
        setConfigApplied(d);
      }
    },
  });

  const handleRunBacktest = useCallback(async () => {
    setBtStatus('running');
    setBtError(null);
    setBtResult(null);
    try {
      const result = await api.runBacktest({
        fee_tier:     btDraft.feeTier,
        trade_amount: parseFloat(btDraft.tradeAmount),
        symbols:      btDraft.symbols.split(',').map((s) => s.trim()),
      });
      setBtResult(result);
      setBtStatus('done');
    } catch (err) {
      setBtError(err?.response?.data?.detail ?? err?.message ?? 'Backtest failed');
      setBtStatus('error');
    }
  }, [btDraft]);

  const handleApplyConfig = useCallback(async () => {
    setConfigSaving(true);
    setConfigError(null);
    try {
      const result = await api.updateConfig({
        fee_tier:             configDraft.feeTier,
        capital_per_leg_usdt: parseFloat(configDraft.capitalPerLeg),
      });
      setConfigApplied(result);
      queryClient.invalidateQueries('liveConfig');
      queryClient.invalidateQueries('simulationStatus');
    } catch (err) {
      setConfigError(err?.response?.data?.detail ?? 'Failed to apply config');
    } finally {
      setConfigSaving(false);
    }
  }, [configDraft]);

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!marketData) return;
    const threshold = marketData.adaptive_threshold ?? 1;
    const b = marketData.binance_price ?? marketData.mid_price ?? null;
    const k = marketData.kraken_price ?? null;

    const rawSpread    = marketData.spread ?? (b != null && k != null ? b - k : null);
    const rawSpreadPct = marketData.spread_pct ?? (rawSpread != null && k ? (rawSpread / k) * 100 : null);
    setHistory((prev) => [
      ...prev,
      {
        time:          formatChartTime(marketData.timestamp),
        binance:       b ?? 0,
        kraken:        k ?? 0,
        spreadPct:     rawSpreadPct != null ? Number(rawSpreadPct.toFixed(4)) : 0,
        spreadAbs:     rawSpread    != null ? Number(rawSpread.toFixed(4))    : 0,
        signalStrength: marketData.signal_strength ?? 0,
        threshold,
      },
    ].slice(-MAX_HISTORY_POINTS));

    const prev = prevPricesRef.current;
    if (prev.binance != null && prev.kraken != null && b != null && k != null) {
      const bDelta = b - prev.binance;
      const kDelta = k - prev.kraken;
      setPriceTrend({
        binance: getRelativePriceClass(bDelta, kDelta),
        kraken: getRelativePriceClass(kDelta, bDelta),
      });
    }

    prevPricesRef.current = { binance: b, kraken: k };
  }, [marketData]);

  useEffect(() => {
    setHistory([]);
    setPriceTrend({ binance: '', kraken: '' });
    prevPricesRef.current = { binance: null, kraken: null };
  }, [selectedSymbol]);

  const activityRows = useMemo(() => {
    return (recentTrades || []).map((trade, idx) => {
      const gross = trade.gross_pnl ?? trade.amount * (trade.sell_price - trade.buy_price);
      const fees = trade.fees ?? 0;
      const side = tradeSide(trade);
      return {
        id: `${trade.timestamp}-${idx}`,
        timestamp: trade.timestamp,
        side,
        route: `${trade.buy_exchange} → ${trade.sell_exchange}`,
        gross,
        fees,
        net: trade.pnl ?? 0,
      };
    });
  }, [recentTrades]);

  const pnlHistory = useMemo(() => {
    if (!recentTrades?.length) return [];
    let cumGross = 0;
    let cumFees = 0;
    let cumNet = 0;
    const sorted = [...recentTrades].reverse();
    return sorted.map((t, i) => {
      const gross = t.gross_pnl ?? t.amount * (t.sell_price - t.buy_price);
      const fees = t.fees ?? 0;
      cumGross += gross;
      cumFees += fees;
      cumNet += t.pnl ?? 0;
      return {
        index: i + 1,
        gross: cumGross,
        fees: cumFees,
        pnl: cumNet,
      };
    });
  }, [recentTrades]);

  const isConnected = isRunning && !marketDataError && !!marketData;
  const isLoading = marketDataLoading || simStatusLoading || tradesLoading;
  const hasChartData = history.length > 0;

  const binancePrice = marketData?.binance_price ?? marketData?.mid_price;
  const krakenPrice = marketData?.kraken_price;
  const spread = marketData?.spread ?? (binancePrice != null && krakenPrice != null ? binancePrice - krakenPrice : null);
  const spreadPct = marketData?.spread_pct ?? (spread != null && krakenPrice ? (spread / krakenPrice) * 100 : null);
  const signalStrength = marketData?.signal_strength ?? 0;
  const adaptiveThreshold = marketData?.adaptive_threshold ?? 1;
  const signalTriggered = signalStrength >= adaptiveThreshold;

  const handleExportCsv = useCallback(() => {
    exportActivityCsv(activityRows);
  }, [activityRows]);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <header className="top-bar">
        <h1 className="top-bar-title">Cross-Exchange Statistical Arbitrage System</h1>
        <div className="top-bar-right">
          <div className="tab-nav">
            <button type="button" className={`tab-btn ${activeTab === 'live' ? 'active' : ''}`} onClick={() => setActiveTab('live')}>Live Monitor</button>
            <button type="button" className={`tab-btn ${activeTab === 'backtest' ? 'active' : ''}`} onClick={() => setActiveTab('backtest')}>Backtesting</button>
          </div>
          <div className="connection-status">
            <span className={`status-dot ${isConnected ? 'connected' : 'disconnected'}`} />
            {isConnected ? 'Connected' : isRunning ? 'Connecting…' : 'Stopped'}
          </div>
          <span className="current-time">{formatTime(currentTime)}</span>
        </div>
      </header>

      <main className="dashboard">
        {activeTab === 'live' && marketDataError && (
          <div className="error-banner">
            Unable to load market data. Check that the backend is running at {API_BASE_URL}.
          </div>
        )}

        {/* ══════════════════════════════════════════════════════════
             BACKTEST TAB
            ══════════════════════════════════════════════════════════ */}
        {activeTab === 'backtest' && (
          <div className="backtest-tab">
            <section>
              <h2 className="section-header">Backtesting Configuration</h2>
              <div className="card">
                <div className="config-grid" style={{ marginBottom: 0 }}>
                  <div className="config-field">
                    <label className="config-label">Fee Tier</label>
                    <select className="config-select" value={btDraft.feeTier}
                      onChange={(e) => setBtDraft((p) => ({ ...p, feeTier: e.target.value }))}>
                      {Object.entries(FEE_TIER_LABELS).map(([k, l]) => (
                        <option key={k} value={k}>{l}</option>
                      ))}
                    </select>
                  </div>
                  <div className="config-field">
                    <label className="config-label">Trade Size (base asset)</label>
                    <input type="number" className="config-input" min="0.0001" step="0.001"
                      value={btDraft.tradeAmount}
                      onChange={(e) => setBtDraft((p) => ({ ...p, tradeAmount: e.target.value }))} />
                  </div>
                  <div className="config-field">
                    <label className="config-label">Symbols</label>
                    <input type="text" className="config-input"
                      value={btDraft.symbols}
                      onChange={(e) => setBtDraft((p) => ({ ...p, symbols: e.target.value }))}
                      placeholder="BTC/USDT,ETH/USDT" />
                  </div>
                  <div className="config-actions">
                    <button type="button" className="btn btn-apply"
                      onClick={handleRunBacktest} disabled={btStatus === 'running'}>
                      {btStatus === 'running' ? 'Running…' : 'Run Backtest'}
                    </button>
                    {btError && <div className="config-error">{btError}</div>}
                  </div>
                </div>
              </div>
            </section>

            {btStatus === 'running' && (
              <div className="card" style={{ textAlign: 'center', padding: 32 }}>
                <div className="config-label" style={{ fontSize: 14 }}>Running backtest against historical data…</div>
                <div className="config-hint" style={{ marginTop: 8 }}>This may take 5–15 seconds depending on data size.</div>
              </div>
            )}

            {btResult && btStatus === 'done' && (
              <>
                {/* Data source notice */}
                {Object.values(btResult.data_sources || {}).some((s) => s === 'synthetic') && (
                  <div className="bt-notice">
                    ⚠ Some symbols are using synthetic data. Run <code>scripts/download_real_data.py</code> for a credible backtest.
                  </div>
                )}

                {/* Summary cards */}
                <section>
                  <h2 className="section-header">
                    Backtest Results — {FEE_TIER_LABELS[btResult.fee_tier] ?? btResult.fee_tier}
                  </h2>
                  <div className="market-overview">
                    {[
                      ['Total Trades',  btResult.summary.total_trades, ''],
                      ['Gross PnL',     btResult.summary.gross_pnl?.toFixed(6),  btResult.summary.gross_pnl >= 0 ? 'positive' : 'negative'],
                      ['Total Fees',    btResult.summary.total_fees?.toFixed(6),  'negative'],
                      ['Net PnL',       btResult.summary.net_pnl?.toFixed(6),    btResult.summary.net_pnl   >= 0 ? 'positive' : 'negative'],
                      ['Win Rate',      `${((btResult.summary.win_rate ?? 0) * 100).toFixed(1)}%`, ''],
                      ['Sharpe Ratio',  btResult.summary.sharpe_ratio?.toFixed(2), ''],
                      ['Max Drawdown',  btResult.summary.max_drawdown?.toFixed(6), 'negative'],
                    ].map(([label, val, cls]) => (
                      <div className="card" key={label}>
                        <div className="card-title">{label}</div>
                        <div className={`card-value ${cls}`} style={{ fontSize: 22 }}>{val ?? '—'}</div>
                      </div>
                    ))}
                  </div>
                </section>

                {/* Per-symbol breakdown */}
                <section>
                  <h2 className="section-header">Symbol Breakdown</h2>
                  <div className="card">
                    <table className="signal-table">
                      <thead><tr><th>Symbol</th><th>Trades</th><th>PnL</th><th>Data Source</th></tr></thead>
                      <tbody>
                        {Object.entries(btResult.symbols).map(([sym, s]) => (
                          <tr key={sym}>
                            <td>{sym}</td>
                            <td>{s.trades}</td>
                            <td className={s.pnl >= 0 ? 'signal-buy' : 'signal-sell'}>{s.pnl?.toFixed(8)}</td>
                            <td>
                              <span className={`data-badge ${s.data_source}`}>{s.data_source}</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>

                {/* Equity curve */}
                {btResult.equity_curve?.length > 0 && (
                  <section>
                    <h2 className="section-header">Equity Curve</h2>
                    <div className="card chart-card chart-card-tall">
                      <div className="chart-container chart-container-tall">
                        <ResponsiveContainer width="100%" height="100%">
                          <ComposedChart data={btResult.equity_curve} margin={{ top: 12, right: 24, left: 8, bottom: 8 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#F0F0F0" />
                            <XAxis dataKey="trade" stroke="#6C757D" fontSize={10} tick={{ fill: '#6C757D' }} label={{ value: 'Trade #', position: 'insideBottomRight', offset: -4, fontSize: 10 }} />
                            <YAxis stroke="#6C757D" fontSize={10} tick={{ fill: '#6C757D' }} tickFormatter={(v) => v.toFixed(4)} />
                            <Tooltip content={<PnlTooltip />} />
                            <ReferenceLine y={0} stroke="#6C757D" strokeDasharray="4 2" />
                            <Area type="monotone" dataKey="cumulative_pnl" name="Cumulative PnL"
                              stroke={btResult.summary.net_pnl >= 0 ? '#198754' : '#DC3545'}
                              fill={btResult.summary.net_pnl >= 0 ? '#d1f0e0' : '#fde8ea'}
                              strokeWidth={2} dot={false} />
                          </ComposedChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  </section>
                )}

                {/* Trade log */}
                {btResult.trades?.length > 0 && (
                  <section>
                    <h2 className="section-header">Trade Log (last {btResult.trades.length})</h2>
                    <div className="card">
                      <div className="signal-table-wrap">
                        <table className="signal-table">
                          <thead>
                            <tr><th>Time</th><th>Symbol</th><th>Route</th><th>Gross PnL</th><th>Fees</th><th>Net PnL</th></tr>
                          </thead>
                          <tbody>
                            {btResult.trades.map((t, i) => (
                              <tr key={i}>
                                <td style={{ fontSize: 11 }}>{t.timestamp?.slice(0, 19).replace('T', ' ')}</td>
                                <td>{t.symbol}</td>
                                <td className="route-cell">{t.buy_exchange} → {t.sell_exchange}</td>
                                <td className={t.gross_pnl >= 0 ? 'signal-buy' : 'signal-sell'}>{t.gross_pnl?.toFixed(6)}</td>
                                <td className="negative">{t.fees?.toFixed(6)}</td>
                                <td className={t.net_pnl >= 0 ? 'signal-buy' : 'signal-sell'}>{t.net_pnl?.toFixed(6)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </section>
                )}

                {btResult.summary.total_trades === 0 && (
                  <div className="card" style={{ textAlign: 'center', padding: 32, color: '#6C757D' }}>
                    <strong>No trades executed</strong> under the <em>{FEE_TIER_LABELS[btResult.fee_tier]}</em> fee tier on this data.
                    <br /><br />
                    This is expected: real fees eliminate any marginal spread captured by the synthetic data.
                    Run <code>scripts/download_real_data.py</code> to use real historical price data.
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ══════════════════════════════════════════════════════════
             LIVE TAB
            ══════════════════════════════════════════════════════════ */}
        {activeTab === 'live' && (<>

        <section>
          <h2 className="section-header">Market Overview</h2>
          
          <div className="market-overview">
            <div className="card">
              <div className="card-title">Binance — {selectedSymbol}</div>
              {isLoading && !binancePrice ? (
                <div className="skeleton skeleton-value" />
              ) : (
                <div className={`card-value price-trend ${priceTrend.binance || ''}`}>
                  {binancePrice?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '—'}
                </div>
              )}
            </div>
            <div className="card">
              <div className="card-title">Kraken — {selectedSymbol}</div>
              {isLoading && !krakenPrice ? (
                <div className="skeleton skeleton-value" />
              ) : (
                <div className={`card-value price-trend ${priceTrend.kraken || ''}`}>
                  {krakenPrice?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '—'}
                </div>
              )}
            </div>
            <div className="card">
              <div className="card-title">Spread</div>
              {isLoading && spread == null ? (
                <div className="skeleton skeleton-value" />
              ) : (
                <>
                  <div className={`card-value ${spread >= 0 ? 'positive' : 'negative'}`}>
                    {spread != null ? `${spread >= 0 ? '+' : ''}${spread.toFixed(2)}` : '—'}
                  </div>
                  <div className={`card-subvalue ${spreadPct >= 0 ? 'positive' : 'negative'}`}>
                    {spreadPct != null ? `${spreadPct >= 0 ? '+' : ''}${spreadPct.toFixed(4)}%` : ''}
                  </div>
                </>
              )}
            </div>
            <div className="card">
              <div className="card-title">Signal Strength</div>
              {isLoading && !marketData ? (
                <div className="skeleton skeleton-value" />
              ) : (
                <>
                  <div className={`zscore-display card-value ${getSignalClass(signalStrength, adaptiveThreshold)}`}>
                    {formatMetric(signalStrength)}
                  </div>
                  <div className="card-subvalue">
                    Threshold: {formatMetric(adaptiveThreshold)}
                    {signalTriggered && ` · ${marketData?.signal} triggered`}
                  </div>
                </>
              )}
            </div>
          </div>
          <p className="chart-legend-hint price-legend-hint">
            Binance/Kraken stay <span className="positive">green</span> or <span className="negative">red</span> until the next tick — whichever exchange moved more vs the other.
          </p>
        </section>

        {/* ── Transaction Model Flow ─────────────────────────────── */}
        <section>
          <h2 className="section-header">Transaction Model — Live State</h2>
          <div className="txn-flow">
            {/* SETUP */}
            <div className="txn-box">
              <div className="txn-label setup">SETUP</div>
              <div className="txn-row"><span className="txn-key">Capital per leg</span><span className="txn-val">{configApplied ? `${configApplied.capital_per_leg_usdt.toLocaleString()} USDT` : '—'}</span></div>
              <div className="txn-row"><span className="txn-key">Implied trade size</span><span className="txn-val">{binancePrice && configApplied ? `≈ ${(configApplied.capital_per_leg_usdt / binancePrice).toFixed(5)} ${selectedSymbol.split('/')[0]}` : '—'}</span></div>
              <div className="txn-row"><span className="txn-key">Fee tier</span><span className="txn-val">{FEE_TIER_LABELS[configApplied?.fee_tier ?? 'retail'] ?? 'Retail'}</span></div>
              <div className="txn-row"><span className="txn-key">Binance taker</span><span className="txn-val">{configApplied ? `${configApplied.binance_taker_pct}%` : '—'}</span></div>
              <div className="txn-row"><span className="txn-key">Kraken taker</span><span className="txn-val">{configApplied ? `${configApplied.kraken_taker_pct}%` : '—'}</span></div>
              <div className="txn-row"><span className="txn-key">Break-even spread</span><span className="txn-val" style={{color:'#DC3545'}}>{configApplied ? `> ${configApplied.break_even_spread_pct}%` : '—'}</span></div>
            </div>

            <div className="txn-arrow">→</div>

            {/* SIGNAL DETECTED */}
            <div className="txn-box">
              <div className="txn-label signal">SIGNAL DETECTED</div>
              <div className="txn-row"><span className="txn-key">Binance price</span><span className="txn-val">{binancePrice?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '—'}</span></div>
              <div className="txn-row"><span className="txn-key">Kraken price</span><span className="txn-val">{krakenPrice?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '—'}</span></div>
              <div className="txn-row">
                <span className="txn-key">Spread</span>
                <span className={`txn-val ${spread != null && spread !== 0 ? (spread > 0 ? 'positive' : 'negative') : ''}`}>
                  {spread != null ? `${spread >= 0 ? '+' : ''}${spread.toFixed(4)} (${spreadPct != null ? spreadPct.toFixed(4) : '—'}%)` : '—'}
                </span>
              </div>
              <div className="txn-row">
                <span className="txn-key">Signal Strength</span>
                <span className={`txn-val ${getSignalClass(signalStrength, adaptiveThreshold)}`}>{formatMetric(signalStrength)}</span>
              </div>
              <div className="txn-row">
                <span className="txn-key">Threshold</span>
                <span className="txn-val">{formatMetric(adaptiveThreshold)}</span>
              </div>
              <div className="txn-row">
                <span className="txn-key">Signal</span>
                <span className={`txn-val ${marketData?.signal === 'BUY' ? 'positive' : marketData?.signal === 'SELL' ? 'negative' : ''}`}>{marketData?.signal ?? 'HOLD'}</span>
              </div>
            </div>

            <div className="txn-arrow">→</div>

            {/* SIMULTANEOUS EXECUTION */}
            <div className={`txn-box ${signalTriggered ? 'txn-box-active' : ''}`}>
              <div className="txn-label execution">SIMULTANEOUS EXECUTION</div>
              {signalTriggered && marketData?.signal !== 'HOLD' ? (
                <>
                  {(() => {
                    const cap   = configApplied?.capital_per_leg_usdt ?? 1000;
                    const base  = selectedSymbol.split('/')[0];
                    const btAmt = binancePrice ? (cap / binancePrice).toFixed(5) : '?';
                    const ktAmt = krakenPrice  ? (cap / krakenPrice).toFixed(5)  : '?';
                    return marketData.signal === 'SELL' ? (
                      <>
                        <div className="txn-exec-leg sell">
                          <span className="exec-side">SELL</span> {btAmt} {base} on Binance<br/>
                          <span className="exec-price">@ {binancePrice?.toFixed(2)} · proceeds ≈ ${(cap * (1 - (configApplied?.binance_taker_pct ?? 0.1) / 100)).toFixed(2)}</span>
                        </div>
                        <div className="txn-exec-leg buy">
                          <span className="exec-side">BUY</span> {ktAmt} {base} on Kraken<br/>
                          <span className="exec-price">@ {krakenPrice?.toFixed(2)} · cost ≈ ${(cap * (1 + (configApplied?.kraken_taker_pct ?? 0.4) / 100)).toFixed(2)}</span>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="txn-exec-leg buy">
                          <span className="exec-side">BUY</span> {btAmt} {base} on Binance<br/>
                          <span className="exec-price">@ {binancePrice?.toFixed(2)} · cost ≈ ${(cap * (1 + (configApplied?.binance_taker_pct ?? 0.1) / 100)).toFixed(2)}</span>
                        </div>
                        <div className="txn-exec-leg sell">
                          <span className="exec-side">SELL</span> {ktAmt} {base} on Kraken<br/>
                          <span className="exec-price">@ {krakenPrice?.toFixed(2)} · proceeds ≈ ${(cap * (1 - (configApplied?.kraken_taker_pct ?? 0.4) / 100)).toFixed(2)}</span>
                        </div>
                      </>
                    );
                  })()}
                  <div className="txn-result">
                    Net position: market-neutral. Spread captured.
                  </div>
                </>
              ) : (
                <div className="txn-waiting">Waiting for z-score ≥ threshold…</div>
              )}
            </div>
          </div>
        </section>

        <section className="charts-stack">
          {/* Spread chart replaces the old Price Comparison */}
          <div className="card chart-card chart-card-tall">
            <div className="card-title">Cross-Exchange Spread</div>
            <p className="chart-legend-hint">
              Bid<sub>Binance</sub> − Mid<sub>Kraken</sub> as a percentage.
              Positive → Binance is expensive; negative → Kraken is expensive.
              <span style={{ marginLeft: 8, color: '#6C757D' }}>|spread| &gt; threshold = arbitrage signal.</span>
            </p>
            {!hasChartData ? (
              <div className="skeleton skeleton-chart-tall" />
            ) : (
              <div className="chart-container chart-container-tall">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={history} margin={{ top: 12, right: 24, left: 8, bottom: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F0F0F0" />
                    <XAxis dataKey="time" stroke="#6C757D" fontSize={11} tick={{ fill: '#6C757D' }} />
                    <YAxis stroke="#6C757D" fontSize={11} tick={{ fill: '#6C757D' }} tickFormatter={(v) => `${v.toFixed(3)}%`} />
                    <Tooltip content={<SpreadTooltip />} />
                    <ReferenceLine y={0} stroke="#ADB5BD" strokeDasharray="4 2" label={{ value: 'Par', position: 'insideLeft', fontSize: 10, fill: '#ADB5BD' }} />
                    <Area type="monotone" dataKey="spreadPct" name="Spread %" dot={false} strokeWidth={2}
                      stroke="#0D6EFD" fill="#DBEAFE" fillOpacity={0.4} {...CHART_ANIMATION} />
                    <Line type="monotone" dataKey="spreadAbs" name="Spread $" dot={false} strokeWidth={0} hide />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          <div className="card chart-card chart-card-tall">
            <div className="card-title">Signal Engine</div>
            <p className="chart-legend-hint">Trade when strength (green) crosses the adaptive threshold (red).</p>
            {!hasChartData ? (
              <div className="skeleton skeleton-chart-tall" />
            ) : (
              <div className="chart-container chart-container-tall">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={history} margin={{ top: 12, right: 24, left: 8, bottom: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F0F0F0" />
                    <XAxis dataKey="time" stroke="#6C757D" fontSize={11} tick={{ fill: '#6C757D' }} />
                    <YAxis stroke="#6C757D" fontSize={11} tick={{ fill: '#6C757D' }} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend />
                    <Line type="monotone" dataKey="signalStrength" name="Signal Strength" stroke="#198754" dot={false} strokeWidth={2.5} {...CHART_ANIMATION} />
                    <Line type="monotone" dataKey="threshold" name="Adaptive Threshold" stroke="#DC3545" dot={false} strokeWidth={2} strokeDasharray="6 4" {...CHART_ANIMATION} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </section>

        <section className="activity-section">
          <div className="card">
            <div className="card-title">Trade Activity</div>
            <p className="chart-legend-hint">
              Executed arbs: gross spread capture, fees (both exchanges), net PnL. Session fees:{' '}
              <strong>{formatUsd(simulationStatus?.total_fees_paid ?? 0)}</strong> USDT
            </p>
            <div className="signal-table-wrap">
              {tradesLoading && !activityRows.length ? (
                <div className="skeleton skeleton-chart" style={{ height: 160 }} />
              ) : activityRows.length === 0 ? (
                <div className="empty-state">No trades yet — activity appears after the first simulated fill</div>
              ) : (
                <table className="signal-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Side</th>
                      <th>Route</th>
                      <th>Gross</th>
                      <th>Fees</th>
                      <th>Net PnL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activityRows.map((row) => (
                      <tr key={row.id}>
                        <td>{new Date(row.timestamp).toLocaleString()}</td>
                        <td className={row.side === 'BUY' ? 'signal-buy' : 'signal-sell'}>{row.side}</td>
                        <td className="route-cell">{row.route}</td>
                        <td className={row.gross >= 0 ? 'signal-buy' : 'signal-sell'}>{formatUsd(row.gross)}</td>
                        <td className="negative">{formatUsd(row.fees)}</td>
                        <td className={row.net >= 0 ? 'signal-buy' : 'signal-sell'}>{formatUsd(row.net)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div className="export-row">
              <button type="button" className="btn btn-export" onClick={handleExportCsv} disabled={!activityRows.length}>
                Export CSV
              </button>
            </div>
          </div>
        </section>

        {/* ── Strategy Configuration Panel ── */}
        <section>
          <h2 className="section-header">Strategy Configuration</h2>
          <div className="card config-panel">
            <div className="config-grid">
              <div className="config-field">
                <label className="config-label" htmlFor="fee-tier-select">Fee Tier</label>
                <select
                  id="fee-tier-select"
                  className="config-select"
                  value={configDraft.feeTier}
                  onChange={(e) => setConfigDraft((p) => ({ ...p, feeTier: e.target.value }))}
                >
                  {Object.entries(FEE_TIER_LABELS).map(([key, label]) => (
                    <option key={key} value={key}>{label}</option>
                  ))}
                </select>
                {configApplied && (
                  <div className="config-hint">
                    Active: {FEE_TIER_LABELS[configApplied.fee_tier] ?? configApplied.fee_tier}
                    &nbsp;·&nbsp;Binance {configApplied.binance_taker_pct}% / Kraken {configApplied.kraken_taker_pct}%
                    &nbsp;·&nbsp;<strong>Break-even spread: {configApplied.break_even_spread_pct}%</strong>
                  </div>
                )}
              </div>

              <div className="config-field">
                <label className="config-label" htmlFor="capital-input">
                  Capital per leg (USDT)
                </label>
                <input
                  id="capital-input"
                  type="number"
                  className="config-input"
                  min="10"
                  step="100"
                  value={configDraft.capitalPerLeg}
                  onChange={(e) => setConfigDraft((p) => ({ ...p, capitalPerLeg: e.target.value }))}
                />
                <div className="config-hint">
                  USDT deployed on each exchange.&nbsp;
                  {binancePrice
                    ? `≈ ${(parseFloat(configDraft.capitalPerLeg || 0) / binancePrice).toFixed(4)} ${selectedSymbol.split('/')[0]} @ live price`
                    : 'Trade size = capital ÷ current ask'}
                </div>
              </div>

              <div className="config-actions">
                <button
                  type="button"
                  className="btn btn-apply"
                  onClick={handleApplyConfig}
                  disabled={configSaving}
                >
                  {configSaving ? 'Applying…' : 'Apply'}
                </button>
                {configError && <div className="config-error">{configError}</div>}
                {configApplied && !configError && (
                  <div className="config-success">
                    ✓ Applied — next trade uses {configApplied.fee_tier}
                  </div>
                )}
              </div>
            </div>

            {/* Fee tier info table */}
            <div className="fee-tier-table-wrap">
              <table className="fee-tier-table">
                <thead>
                  <tr>
                    <th>Tier</th>
                    <th>Binance Taker</th>
                    <th>Kraken Taker</th>
                    <th>~30d Vol Required</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ['retail',         '0.100%', '0.400%', '—'],
                    ['retail_bnb',     '0.075%', '0.400%', '— (hold BNB)'],
                    ['vip3',           '0.060%', '0.240%', '$20M'],
                    ['vip5',           '0.048%', '0.200%', '$150M'],
                    ['vip9',           '0.024%', '0.100%', '$5B'],
                    ['market_maker',   '0.020%', '0.100%', '$100M'],
                    ['dekabank_proxy', '0.040%', '0.140%', '$100M (negotiated)'],
                    ['zero_fee',       '0.000%', '0.000%', 'Illustrative only'],
                  ].map(([key, bn, kr, vol]) => (
                    <tr key={key} className={configApplied?.fee_tier === key ? 'active-tier-row' : ''}>
                      <td>{FEE_TIER_LABELS[key]}</td>
                      <td>{bn}</td>
                      <td>{kr}</td>
                      <td>{vol}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="bottom-section">
          <div className="card controls-panel">
            <div className="card-title">System Controls &amp; Stats</div>
            <div className="control-row">
              <button type="button" className="btn btn-start" onClick={() => setIsRunning(true)} disabled={isRunning}>
                Start
              </button>
              <button type="button" className="btn btn-stop" onClick={() => setIsRunning(false)} disabled={!isRunning}>
                Stop
              </button>
              <select
                className="pair-select"
                value={selectedSymbol}
                onChange={(e) => setSelectedSymbol(e.target.value)}
                aria-label="Trading pair"
              >
                {SYMBOLS.map((sym) => (
                  <option key={sym} value={sym}>{sym}</option>
                ))}
              </select>
            </div>

            <div className="stats-grid">
              <div className="stat-item">
                <div className="stat-label">Total Trades</div>
                <div className="stat-value">{simulationStatus?.total_trades ?? 0}</div>
              </div>
              <div className="stat-item">
                <div className="stat-label">Current Signal</div>
                <div className="stat-value">{marketData?.signal ?? 'HOLD'}</div>
              </div>
              <div className="stat-item">
                <div className="stat-label">Cumulative PnL</div>
                <div className={`stat-value ${(simulationStatus?.total_pnl ?? 0) >= 0 ? 'positive' : 'negative'}`}>
                  {simulationStatus?.total_pnl?.toFixed(6) ?? '0.000000'}
                </div>
              </div>
              <div className="stat-item">
                <div className="stat-label">Win Rate</div>
                <div className="stat-value">{simulationStatus?.win_rate?.toFixed(1) ?? '0.0'}%</div>
              </div>
              <div className="stat-item">
                <div className="stat-label">Total Fees</div>
                <div className="stat-value negative">{formatUsd(simulationStatus?.total_fees_paid ?? 0)}</div>
              </div>
              <div className="stat-item">
                <div className="stat-label">Sharpe Ratio</div>
                <div className="stat-value">
                  {simulationStatus?.sharpe_ratio != null ? simulationStatus.sharpe_ratio.toFixed(2) : 'N/A'}
                </div>
              </div>
              <div className="stat-item">
                <div className="stat-label">Max Drawdown</div>
                <div className="stat-value negative">
                  {simulationStatus?.max_drawdown != null
                    ? formatPercent(simulationStatus.max_drawdown)
                    : 'N/A'}
                </div>
              </div>
            </div>

            {isFetching && isRunning && (
              <div className="card-subvalue" style={{ marginTop: 12 }}>Refreshing data…</div>
            )}
          </div>

          <div className="card pnl-chart-card">
            <div className="card-title">Cumulative Performance</div>
            <p className="chart-legend-hint">
              <span style={{ color: '#86c99a' }}>—</span> Gross income &nbsp;
              <span style={{ color: '#adb5bd' }}>---</span> Fees &nbsp;
              <span style={{ color: '#198754', fontWeight: 600 }}>—</span> Net PnL
            </p>
            {pnlHistory.length === 0 ? (
              <div className="empty-state">PnL breakdown appears after trades execute</div>
            ) : (
              <div className="chart-container pnl-chart-container">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={pnlHistory} margin={{ top: 12, right: 24, left: 8, bottom: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F0F0F0" />
                    <XAxis dataKey="index" stroke="#6C757D" fontSize={10} tick={{ fill: '#6C757D' }} />
                    <YAxis stroke="#6C757D" fontSize={10} tick={{ fill: '#6C757D' }} />
                    <Tooltip content={<PnlTooltip />} />
                    <Legend />
                    <Area
                      type="monotone"
                      dataKey="gross"
                      name="Gross (income)"
                      stroke="#86c99a"
                      fill="#86c99a"
                      fillOpacity={0.12}
                      strokeWidth={1}
                      {...CHART_ANIMATION}
                    />
                    <Line
                      type="monotone"
                      dataKey="fees"
                      name="Fees (expense)"
                      stroke="#adb5bd"
                      strokeWidth={1.5}
                      strokeDasharray="4 4"
                      dot={false}
                      {...CHART_ANIMATION}
                    />
                    <Line
                      type="monotone"
                      dataKey="pnl"
                      name="Net PnL"
                      stroke={(simulationStatus?.total_pnl ?? 0) >= 0 ? '#198754' : '#DC3545'}
                      strokeWidth={3}
                      dot={false}
                      {...CHART_ANIMATION}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </section>
        </>)}
      </main>
    </ThemeProvider>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  );
}
