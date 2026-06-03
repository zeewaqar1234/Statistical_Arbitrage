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
  runHistoricalBacktest: async (payload) => {
    const { data } = await axios.post(`${API_BASE_URL}/api/v1/bsdex/historical_backtest`, payload, {
      timeout: 120000, headers: { 'Content-Type': 'application/json' },
    });
    return data;
  },
  // BSDEX vs World endpoints
  bsdexStatus: async () => {
    try {
      const { data } = await axios.get(`${API_BASE_URL}/api/v1/bsdex/status`, { timeout: 8000 });
      return data;
    } catch { return null; }
  },
  bsdexTrades: async (limit = 30) => {
    try {
      const { data } = await axios.get(`${API_BASE_URL}/api/v1/bsdex/trades?limit=${limit}`, { timeout: 8000 });
      return Array.isArray(data) ? data : [];
    } catch { return []; }
  },
  bsdexMarket: async (market) => {
    try {
      const { data } = await axios.get(`${API_BASE_URL}/api/v1/bsdex/market/${market}`, { timeout: 8000 });
      return data;
    } catch { return null; }
  },
  bsdexSpreadSeries: async (market, n = 200) => {
    try {
      const { data } = await axios.get(`${API_BASE_URL}/api/v1/bsdex/spread_series/${market}?n=${n}`, { timeout: 8000 });
      return Array.isArray(data) ? data : [];
    } catch { return []; }
  },
  bsdexVolumeTiers: async () => {
    try {
      const { data } = await axios.get(`${API_BASE_URL}/api/v1/bsdex/volume_tiers`, { timeout: 8000 });
      return Array.isArray(data) ? data : [];
    } catch { return []; }
  },
  bsdexSetConfig: async (payload) => {
    const { data } = await axios.post(`${API_BASE_URL}/api/v1/bsdex/config`, payload, {
      timeout: 8000, headers: { 'Content-Type': 'application/json' },
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

function BsdexSpreadTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const pct = payload.find((p) => p.dataKey === 'spreadPct');
  const eur = payload.find((p) => p.dataKey === 'spreadEur');
  return (
    <div className="pnl-tooltip" style={tooltipStyle}>
      <div style={{ marginBottom: 4, fontWeight: 600, color: '#6C757D', fontSize: 11 }}>{label}</div>
      {pct && <div style={{ color: pct.color, fontSize: 12 }}>Spread %: {Number(pct.value).toFixed(4)}%</div>}
      {eur && <div style={{ color: '#adb5bd', fontSize: 12 }}>Spread EUR: €{Number(eur.value).toFixed(2)}</div>}
    </div>
  );
}

function AppContent() {
  const [isRunning, setIsRunning] = useState(true);
  const [currentTime, setCurrentTime] = useState(new Date());

  // Tab navigation
  const [activeTab, setActiveTab] = useState('bsdex');

  // Backtesting state
  // BSDEX Historical Backtest state
  const [hbtSymbol,      setHbtSymbol]      = useState('btc-eur');
  const [hbtStartDt,     setHbtStartDt]     = useState('');        // datetime-local string
  const [hbtEndDt,       setHbtEndDt]       = useState('');
  const [hbtFeeMode,     setHbtFeeMode]     = useState('auto');
  const [hbtTierIdx,     setHbtTierIdx]     = useState(1);          // index into bsdexVolumeTiers
  const [hbtFeeA,        setHbtFeeA]        = useState(0.0012);
  const [hbtFeeB,        setHbtFeeB]        = useState(0.0006);
  const [hbtCapital,     setHbtCapital]     = useState(1000);
  const [hbtStatus,      setHbtStatus]      = useState('idle');     // idle | running | done | error
  const [hbtResult,      setHbtResult]      = useState(null);
  const [hbtError,       setHbtError]       = useState(null);

  // BSDEX tab state
  const [bsdexMarket, setBsdexMarket]           = useState('btc-eur');
  const [bsdexCapitalEur, setBsdexCapitalEur]   = useState(1000);
  const [bsdexFeeMode, setBsdexFeeMode]         = useState('auto');   // 'auto' | 'manual'
  const [bsdexTierIdx, setBsdexTierIdx]         = useState(1);        // index into volume tiers
  const [bsdexFeeA, setBsdexFeeA]               = useState(0.0012);   // Bitstamp taker (decimal)
  const [bsdexFeeB, setBsdexFeeB]               = useState(0.0006);   // LMAX taker (decimal)
  const [bsdexConfigSaving, setBsdexConfigSaving] = useState(false);
  const [bsdexConfigApplied, setBsdexConfigApplied] = useState(false);
  const bsdexPrevPricesRef = useRef({ venueA: null, venueB: null });
  const [bsdexPriceTrend, setBsdexPriceTrend]   = useState({ venueA: '', venueB: '' });

  // BSDEX queries — active when BSDEX tab or backtest tab is open
  const bsdexPollInterval = (isRunning && activeTab === 'bsdex') ? REFRESH_INTERVAL : false;
  const { data: bsdexStatus } = useQuery('bsdexStatus', api.bsdexStatus, { refetchInterval: bsdexPollInterval, retry: 1 });
  const { data: bsdexTrades = [] } = useQuery('bsdexTrades', () => api.bsdexTrades(30), { refetchInterval: bsdexPollInterval, retry: 1 });
  const { data: bsdexMarketData } = useQuery(['bsdexMarket', bsdexMarket], () => api.bsdexMarket(bsdexMarket), { refetchInterval: bsdexPollInterval, retry: 1 });
  const { data: bsdexSeries = [] } = useQuery(['bsdexSeries', bsdexMarket], () => api.bsdexSpreadSeries(bsdexMarket, 200), { refetchInterval: bsdexPollInterval, retry: 1 });
  const { data: bsdexVolumeTiers = [] } = useQuery('bsdexVolumeTiers', api.bsdexVolumeTiers, { refetchInterval: 60000, retry: 1,
    onSuccess: (tiers) => {
      if (tiers && tiers.length > bsdexTierIdx) {
        const t = tiers[bsdexTierIdx];
        setBsdexFeeA(t.bitstamp_taker);
        setBsdexFeeB(t.lmax_taker);
      }
    }
  });

  // Sync fee inputs when tier selector changes in auto mode
  const handleBsdexTierChange = useCallback((idx) => {
    setBsdexTierIdx(idx);
    if (bsdexFeeMode === 'auto' && bsdexVolumeTiers[idx]) {
      setBsdexFeeA(bsdexVolumeTiers[idx].bitstamp_taker);
      setBsdexFeeB(bsdexVolumeTiers[idx].lmax_taker);
    }
  }, [bsdexFeeMode, bsdexVolumeTiers]);

  const handleBsdexFeeModeChange = useCallback((mode) => {
    setBsdexFeeMode(mode);
    if (mode === 'auto' && bsdexVolumeTiers[bsdexTierIdx]) {
      setBsdexFeeA(bsdexVolumeTiers[bsdexTierIdx].bitstamp_taker);
      setBsdexFeeB(bsdexVolumeTiers[bsdexTierIdx].lmax_taker);
    }
  }, [bsdexTierIdx, bsdexVolumeTiers]);

  const handleBsdexApplyConfig = useCallback(async () => {
    setBsdexConfigSaving(true);
    setBsdexConfigApplied(false);
    try {
      const tier = bsdexVolumeTiers[bsdexTierIdx];
      await api.bsdexSetConfig({
        venue_a_taker: bsdexFeeA,
        venue_b_taker: bsdexFeeB,
        tier_label:    bsdexFeeMode === 'auto' && tier ? tier.label : 'manual',
        tier_idx:      bsdexFeeMode === 'auto' ? bsdexTierIdx : -1,
        fee_mode:      bsdexFeeMode,
        capital_eur:   bsdexCapitalEur,
      });
      queryClient.invalidateQueries('bsdexStatus');
      setBsdexConfigApplied(true);
      setTimeout(() => setBsdexConfigApplied(false), 3000);
    } catch (e) {
      console.error('Failed to apply BSDEX config', e);
    } finally {
      setBsdexConfigSaving(false);
    }
  }, [bsdexFeeA, bsdexFeeB, bsdexFeeMode, bsdexTierIdx, bsdexVolumeTiers, bsdexCapitalEur]);

  // Formatted BSDEX spread series for chart
  const bsdexChartData = useMemo(() =>
    bsdexSeries.slice(-150).map((p, i) => ({
      index: i,
      time: p.ts ? new Date(p.ts).toLocaleTimeString('en-US', { hour12: false }) : '',
      spreadPct: typeof p.spread_pct === 'number' ? parseFloat(p.spread_pct.toFixed(4)) : null,
      spreadEur: typeof p.spread_eur === 'number' ? parseFloat(p.spread_eur.toFixed(2)) : null,
      zScore: typeof p.z_score === 'number' ? parseFloat(p.z_score.toFixed(3)) : null,
      threshold: typeof p.threshold === 'number' ? parseFloat(p.threshold.toFixed(3)) : null,
    })), [bsdexSeries]);

  // Break-even derived from local fee state (always up to date)
  const bsdexBreakevenPct = (bsdexFeeA + bsdexFeeB) * 100;

  const venueAMid = useMemo(() => {
    if (!bsdexMarketData?.a_bid || !bsdexMarketData?.a_ask) return null;
    return (bsdexMarketData.a_bid + bsdexMarketData.a_ask) / 2;
  }, [bsdexMarketData]);

  const venueBMid = useMemo(() => {
    if (!bsdexMarketData?.b_bid || !bsdexMarketData?.b_ask) return null;
    return (bsdexMarketData.b_bid + bsdexMarketData.b_ask) / 2;
  }, [bsdexMarketData]);

  const bsdexZScore          = bsdexMarketData?.z_score ?? null;
  const bsdexThreshold       = bsdexMarketData?.threshold ?? null;
  const bsdexSpread          = bsdexMarketData?.spread_eur ?? null;
  const bsdexSpreadPct       = bsdexMarketData?.spread_pct ?? null;
  const bsdexSignalState     = bsdexMarketData?.signal_state ?? 'HOLD';
  const bsdexSignalTriggered = bsdexSignalState === 'SIGNAL';
  const bsdexSignalGated     = bsdexSignalState === 'SIGNAL_GATED';
  const bsdexSignalCooldown  = bsdexSignalState === 'SIGNAL_COOLDOWN';
  const bsdexBase            = bsdexMarket.split('-')[0].toUpperCase();

  // Price trend for Venue A / B (same pattern as Binance/Kraken)
  useEffect(() => {
    if (!bsdexMarketData) return;
    const newA = bsdexMarketData.a_bid;
    const newB = bsdexMarketData.b_bid;
    const prev = bsdexPrevPricesRef.current;
    const aDelta = prev.venueA != null ? newA - prev.venueA : 0;
    const bDelta = prev.venueB != null ? newB - prev.venueB : 0;
    setBsdexPriceTrend({
      venueA: prev.venueA != null ? (aDelta > 0 ? 'positive' : aDelta < 0 ? 'negative' : '') : '',
      venueB: prev.venueB != null ? (bDelta > 0 ? 'positive' : bDelta < 0 ? 'negative' : '') : '',
    });
    bsdexPrevPricesRef.current = { venueA: newA, venueB: newB };
  }, [bsdexMarketData]);

  // Sync HBT fee inputs when tier changes
  const handleHbtTierChange = useCallback((idx) => {
    setHbtTierIdx(idx);
    if (hbtFeeMode === 'auto' && bsdexVolumeTiers[idx]) {
      setHbtFeeA(bsdexVolumeTiers[idx].bitstamp_taker);
      setHbtFeeB(bsdexVolumeTiers[idx].lmax_taker);
    }
  }, [hbtFeeMode, bsdexVolumeTiers]);

  const handleHbtFeeModeChange = useCallback((mode) => {
    setHbtFeeMode(mode);
    if (mode === 'auto' && bsdexVolumeTiers[hbtTierIdx]) {
      setHbtFeeA(bsdexVolumeTiers[hbtTierIdx].bitstamp_taker);
      setHbtFeeB(bsdexVolumeTiers[hbtTierIdx].lmax_taker);
    }
  }, [hbtTierIdx, bsdexVolumeTiers]);

  const handleRunHistoricalBacktest = useCallback(async () => {
    if (!hbtStartDt || !hbtEndDt) {
      setHbtError('Please select both start and end date/time.');
      return;
    }
    setHbtStatus('running');
    setHbtError(null);
    setHbtResult(null);
    try {
      const result = await api.runHistoricalBacktest({
        symbol:        hbtSymbol,
        start_dt:      new Date(hbtStartDt).toISOString(),
        end_dt:        new Date(hbtEndDt).toISOString(),
        venue_a_taker: hbtFeeA,
        venue_b_taker: hbtFeeB,
        capital_eur:   hbtCapital,
        tier_label:    hbtFeeMode === 'auto' && bsdexVolumeTiers[hbtTierIdx]
                         ? bsdexVolumeTiers[hbtTierIdx].label
                         : 'manual',
      });
      setHbtResult(result);
      setHbtStatus('done');
    } catch (err) {
      setHbtError(err?.response?.data?.detail ?? err?.message ?? 'Backtest failed');
      setHbtStatus('error');
    }
  }, [hbtSymbol, hbtStartDt, hbtEndDt, hbtFeeA, hbtFeeB, hbtCapital,
      hbtFeeMode, hbtTierIdx, bsdexVolumeTiers]);

  // Excel export via SheetJS
  const handleExportExcel = useCallback(() => {
    if (!hbtResult) return;
    import('xlsx').then((XLSX) => {
      const wb = XLSX.utils.book_new();

      // Sheet 1: Summary
      const summary = hbtResult.summary;
      const sumRows = Object.entries(summary).map(([k, v]) => ({ Field: k, Value: v }));
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(sumRows), 'Summary');

      // Sheet 2: Trades
      if (hbtResult.trades.length > 0) {
        const tradeRows = hbtResult.trades.map((t) => ({
          Timestamp:     t.ts_str?.slice(0, 19).replace('T', ' '),
          Direction:     t.direction,
          'Spread %':   t.spread_pct,
          'Z-Score':    t.z_score,
          'Price A (€)': t.price_a_eur,
          'Price B (€)': t.price_b_eur,
          'Amount':     t.amount,
          'Gross (€)':  t.gross_eur,
          'Fees (€)':   t.fees_eur,
          'Net PnL (€)': t.pnl_eur,
          'Buy Exchange':  t.buy_exchange,
          'Sell Exchange': t.sell_exchange,
        }));
        XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(tradeRows), 'Trades');
      }

      // Sheet 3: Spread Series (downsampled)
      if (hbtResult.spread_series.length > 0) {
        const spreadRows = hbtResult.spread_series.map((p) => ({
          Timestamp:  p.ts_str?.slice(0, 19).replace('T', ' '),
          'Spread %': p.spread_pct,
          'Z-Score':  p.z_score,
          Threshold:  p.threshold,
        }));
        XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(spreadRows), 'Spread Series');
      }

      const sym = hbtSymbol.replace('-', '').toUpperCase();
      const dateStr = hbtStartDt?.slice(0, 10) ?? 'bt';
      XLSX.writeFile(wb, `BSDEX_Backtest_${sym}_${dateStr}.xlsx`);
    });
  }, [hbtResult, hbtSymbol, hbtStartDt]);


  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);


  // isConnected: derive from BSDEX market data since we only have the BSDEX tab now
  const isConnected = isRunning && !!bsdexMarketData;


  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <header className="top-bar">
        <h1 className="top-bar-title">Cross-Exchange Statistical Arbitrage System</h1>
        <div className="top-bar-right">
          <div className="tab-nav">
            <button type="button" className={`tab-btn tab-btn-bsdex ${activeTab === 'bsdex' ? 'active' : ''}`} onClick={() => setActiveTab('bsdex')}>BSDEX vs World</button>
            <button type="button" className={`tab-btn ${activeTab === 'backtest' ? 'active' : ''}`} onClick={() => setActiveTab('backtest')}>BSDEX Backtest</button>
          </div>
          <div className="connection-status">
            <span className={`status-dot ${isConnected ? 'connected' : 'disconnected'}`} />
            {isConnected ? 'Connected' : isRunning ? 'Connecting…' : 'Stopped'}
          </div>
          <span className="current-time">{formatTime(currentTime)}</span>
        </div>
      </header>

      <main className="dashboard">

        {/* ══════════════════════════════════════════════════════════
             BACKTEST TAB
            ══════════════════════════════════════════════════════════ */}
        {/* ══════════════════════════════════════════════════════════
             BSDEX HISTORICAL BACKTEST TAB
            Real 1-minute OHLCV from Bitstamp (EUR) + Binance (USDT→EUR)
            Same spread/z-score logic as the live BSDEX vs World strategy
            ══════════════════════════════════════════════════════════ */}
        {activeTab === 'backtest' && (
          <div className="backtest-tab">

            {/* ── Config card ──────────────────────────────────────── */}
            <section>
              <h2 className="section-header">BSDEX vs World — Historical Backtest</h2>
              <div className="card config-panel">
                <p className="chart-legend-hint" style={{ marginBottom: 14 }}>
                  Fetches <strong>real 1-minute OHLCV</strong> from Bitstamp (EUR) and Binance (USDT→EUR via Frankfurter/ECB FX).
                  Runs the same spread / z-score logic as the live strategy (60-minute rolling window, threshold 1.5σ, 30-minute trade cooldown).
                  All prices and PnL in <strong>EUR</strong>. Max range: 7 days.
                </p>

                <div className="config-grid">
                  {/* Symbol + Date range */}
                  <div className="config-field">
                    <label className="config-label">Market</label>
                    <select className="config-input" value={hbtSymbol} onChange={(e) => setHbtSymbol(e.target.value)}>
                      <option value="btc-eur">BTC/EUR (Bitstamp BTC/EUR vs Binance BTC/USDT→EUR)</option>
                      <option value="eth-eur">ETH/EUR (Bitstamp ETH/EUR vs Binance ETH/USDT→EUR)</option>
                    </select>
                  </div>
                  <div className="config-field">
                    <label className="config-label">Start date &amp; time (UTC)</label>
                    <input type="datetime-local" className="config-input"
                      value={hbtStartDt}
                      onChange={(e) => setHbtStartDt(e.target.value)} />
                  </div>
                  <div className="config-field">
                    <label className="config-label">End date &amp; time (UTC)</label>
                    <input type="datetime-local" className="config-input"
                      value={hbtEndDt}
                      onChange={(e) => setHbtEndDt(e.target.value)} />
                  </div>

                  {/* Capital */}
                  <div className="config-field">
                    <label className="config-label">Capital per leg (EUR)</label>
                    <div className="fee-input-wrap">
                      <input type="number" className="config-input fee-pct-input"
                        min="10" step="100" value={hbtCapital}
                        onChange={(e) => setHbtCapital(parseFloat(e.target.value) || 1000)} />
                      <span className="fee-unit">EUR</span>
                    </div>
                    <div className="config-hint">EUR deployed per venue per trade.</div>
                  </div>
                </div>

                {/* Fee selection — same UI as BSDEX vs World tab */}
                <div style={{ marginTop: 12 }}>
                  <div className="fee-mode-row">
                    <label className="fee-mode-opt">
                      <input type="radio" name="hbtFeeMode" value="auto" checked={hbtFeeMode === 'auto'} onChange={() => handleHbtFeeModeChange('auto')} />
                      {' '}Volume tier (auto)
                    </label>
                    <label className="fee-mode-opt">
                      <input type="radio" name="hbtFeeMode" value="manual" checked={hbtFeeMode === 'manual'} onChange={() => handleHbtFeeModeChange('manual')} />
                      {' '}Manual fees
                    </label>
                  </div>

                  {hbtFeeMode === 'auto' && (
                    <div className="config-field">
                      <label className="config-label">30-Day USD Trading Volume</label>
                      <select className="config-input" value={hbtTierIdx} onChange={(e) => handleHbtTierChange(parseInt(e.target.value))}>
                        {bsdexVolumeTiers.map((t, i) => (
                          <option key={i} value={i}>
                            {t.label} — Bitstamp: {(t.bitstamp_taker * 100).toFixed(2)}% · LMAX: {(t.lmax_taker * 100).toFixed(2)}% · B/E: {((t.bitstamp_taker + t.lmax_taker) * 100).toFixed(2)}%
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  <div className="fee-inputs-row">
                    <div className="fee-input-group">
                      <label className="config-label">Venue A — Bitstamp taker</label>
                      <div className="fee-input-wrap">
                        <input type="number" className="config-input fee-pct-input"
                          min="0" max="5" step="0.001"
                          value={(hbtFeeA * 100).toFixed(3)}
                          readOnly={hbtFeeMode === 'auto'}
                          style={hbtFeeMode === 'auto' ? { background: '#F8F9FA', cursor: 'not-allowed' } : {}}
                          onChange={(e) => setHbtFeeA(Math.max(0, parseFloat(e.target.value) || 0) / 100)} />
                        <span className="fee-unit">%</span>
                      </div>
                    </div>
                    <div className="fee-input-group">
                      <label className="config-label">Venue B — LMAX Digital taker</label>
                      <div className="fee-input-wrap">
                        <input type="number" className="config-input fee-pct-input"
                          min="0" max="5" step="0.001"
                          value={(hbtFeeB * 100).toFixed(3)}
                          readOnly={hbtFeeMode === 'auto'}
                          style={hbtFeeMode === 'auto' ? { background: '#F8F9FA', cursor: 'not-allowed' } : {}}
                          onChange={(e) => setHbtFeeB(Math.max(0, parseFloat(e.target.value) || 0) / 100)} />
                        <span className="fee-unit">%</span>
                      </div>
                    </div>
                  </div>

                  <div className="breakeven-banner" style={{ marginTop: 10 }}>
                    Break-even spread: <strong>{((hbtFeeA + hbtFeeB) * 100).toFixed(3)}%</strong>
                    <span className="breakeven-detail">
                      ({(hbtFeeA * 100).toFixed(3)}% + {(hbtFeeB * 100).toFixed(3)}% combined taker) — trade fires only when |spread| exceeds this
                    </span>
                  </div>
                </div>

                <div className="config-actions" style={{ marginTop: 16 }}>
                  <button type="button" className="btn btn-apply"
                    onClick={handleRunHistoricalBacktest}
                    disabled={hbtStatus === 'running'}>
                    {hbtStatus === 'running' ? 'Fetching data & running…' : 'Run Backtest'}
                  </button>
                  {hbtResult && hbtStatus === 'done' && (
                    <button type="button" className="btn btn-secondary" onClick={handleExportExcel}
                      style={{ marginLeft: 12 }}>
                      Export to Excel
                    </button>
                  )}
                  {hbtError && <div className="config-error" style={{ marginTop: 8 }}>{hbtError}</div>}
                </div>
              </div>
            </section>

            {/* ── Running spinner ───────────────────────────────────── */}
            {hbtStatus === 'running' && (
              <div className="card" style={{ textAlign: 'center', padding: 40 }}>
                <div className="config-label" style={{ fontSize: 15 }}>
                  Fetching real 1-minute OHLCV from Bitstamp &amp; Binance…
                </div>
                <div className="config-hint" style={{ marginTop: 10 }}>
                  Depending on the date range this takes 5–30 seconds (live exchange API calls, no pre-cached data).
                </div>
              </div>
            )}

            {/* ── Results ───────────────────────────────────────────── */}
            {hbtResult && hbtStatus === 'done' && (() => {
              const s = hbtResult.summary;
              const netPos = s.total_pnl_eur >= 0;
              const beStr  = `${s.breakeven_spread_pct?.toFixed(3)}%`;
              return (
                <>
                  {/* ── Summary KPI strip ─────────────────────────────── */}
                  <section>
                    <h2 className="section-header">
                      Results — {s.symbol} · {s.start_dt?.slice(0,10)} → {s.end_dt?.slice(0,10)}
                      {' '}({s.duration_hours}h · {s.candles_processed?.toLocaleString()} candles)
                    </h2>

                    {/* Row 1: P&L trio — always shows gross → fees → net so viewer can verify */}
                    <div className="market-overview" style={{ gridTemplateColumns: 'repeat(3, 1fr)', marginBottom: 8 }}>
                      {[
                        ['Gross PnL',  `€${s.gross_pnl_eur?.toFixed(4)}`,  s.gross_pnl_eur >= 0 ? 'positive' : 'negative', 'Price gain before fees'],
                        ['Total Fees', `−€${s.total_fees_eur?.toFixed(4)}`, 'negative', 'Both legs combined'],
                        ['Net PnL',   `€${s.total_pnl_eur?.toFixed(4)}`,   netPos ? 'positive' : 'negative', 'Gross − Fees (exact)'],
                      ].map(([label, val, cls, sub]) => (
                        <div className="card" key={label}>
                          <div className="card-title">{label}</div>
                          <div className={`card-value ${cls}`} style={{ fontSize: 22 }}>{val ?? '—'}</div>
                          <div className="card-subvalue">{sub}</div>
                        </div>
                      ))}
                    </div>

                    {/* Row 2: operational metrics */}
                    <div className="market-overview" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
                      {[
                        ['Total Trades',    s.total_trades,                                   '',         ''],
                        ['Win Rate',        `${s.win_rate_pct?.toFixed(1)}%`,                 s.win_rate_pct > 50 ? 'positive' : '', ''],
                        ['Max Drawdown',    `€${s.max_drawdown_eur?.toFixed(4)}`,             'negative', ''],
                        ['Allocated VaR',  `€${s.capital_eur?.toLocaleString()} / leg`,       '',         ''],
                      ].map(([label, val, cls]) => (
                        <div className="card" key={label}>
                          <div className="card-title">{label}</div>
                          <div className={`card-value ${cls}`} style={{ fontSize: 18 }}>{val ?? '—'}</div>
                        </div>
                      ))}
                    </div>

                    {/* Microstructure parameter table */}
                    <div className="card" style={{ marginTop: 10, padding: '14px 18px' }}>
                      <div className="card-title" style={{ marginBottom: 10 }}>Strategy Parameters &amp; Operational Safeguards</div>
                      <table className="param-table">
                        <thead>
                          <tr><th>Parameter</th><th>Value</th><th>Operational Safeguard</th></tr>
                        </thead>
                        <tbody>
                          <tr>
                            <td>Signal threshold</td>
                            <td>{s.zscore_threshold}σ rolling z-score</td>
                            <td>Adaptive volatility tracking</td>
                          </tr>
                          <tr>
                            <td>Lookback window</td>
                            <td>{s.zscore_window_min} min ({s.candles_processed?.toLocaleString()} intervals)</td>
                            <td>1-min OHLCV replay (not tick data)</td>
                          </tr>
                          <tr>
                            <td>Combined friction drag</td>
                            <td>{(s.breakeven_spread_pct)?.toFixed(3)}% ({((s.venue_a_taker_pct ?? 0) + (s.venue_b_taker_pct ?? 0)).toFixed(3)} bp)</td>
                            <td>Break-even gate on every trade</td>
                          </tr>
                          <tr>
                            <td>Cooldown window</td>
                            <td>{s.trade_cooldown_min} min</td>
                            <td>Toxic flow &amp; mean-reversion guard</td>
                          </tr>
                          <tr>
                            <td>FX conversion</td>
                            <td>ECB rate via Frankfurter API</td>
                            <td>Refreshed every 60 s (daily fixing)</td>
                          </tr>
                          <tr>
                            <td>Execution price model</td>
                            <td>1-min close (no bid-ask simulated)</td>
                            <td>Understates real cost; treat as lower bound</td>
                          </tr>
                          <tr>
                            <td>Volume weighting</td>
                            <td>Not applied (volume = 0 in OHLCV replay)</td>
                            <td>Backtest uses raw z-score only — consistent with live BSDEX trigger</td>
                          </tr>
                          <tr>
                            <td>Data sources</td>
                            <td colSpan={2}>{s.data_sources}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </section>

                  {/* ── Equity curve ─────────────────────────────────── */}
                  {hbtResult.equity_curve?.length > 1 && (
                    <section>
                      <h2 className="section-header">Cumulative Net PnL — EUR</h2>
                      <div className="card chart-card chart-card-tall">
                        <div className="chart-container chart-container-tall">
                          <ResponsiveContainer width="100%" height="100%">
                            <ComposedChart data={hbtResult.equity_curve} margin={{ top: 12, right: 24, left: 8, bottom: 8 }}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#F0F0F0" />
                              <XAxis dataKey="ts_str" stroke="#6C757D" fontSize={10} tick={{ fill: '#6C757D' }}
                                tickFormatter={(v) => v?.slice(11, 16)} />
                              <YAxis stroke="#6C757D" fontSize={10} tick={{ fill: '#6C757D' }}
                                tickFormatter={(v) => `€${v.toFixed(2)}`} />
                              <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`€${v.toFixed(4)}`, 'Cumulative Net PnL']} />
                              <ReferenceLine y={0} stroke="#6C757D" strokeDasharray="4 2" />
                              <Area type="monotone" dataKey="cumulative_pnl" name="Net PnL (€)"
                                stroke={netPos ? '#198754' : '#DC3545'}
                                fill={netPos ? '#d1f0e0' : '#fde8ea'}
                                strokeWidth={2} dot={false} isAnimationActive={false} />
                            </ComposedChart>
                          </ResponsiveContainer>
                        </div>
                      </div>
                    </section>
                  )}

                  {/* ── Spread + Z-score charts ───────────────────────── */}
                  {hbtResult.spread_series?.length > 1 && (
                    <section className="charts-stack">
                      <div className="card chart-card chart-card-tall">
                        <div className="card-title">Historical Spread % — Bitstamp vs Binance→EUR</div>
                        <p className="chart-legend-hint">
                          Positive = Bitstamp expensive (sell A, buy B). Dashed lines = ±{beStr} break-even.
                          Spread must exceed break-even for a trade to fire.
                        </p>
                        <div className="chart-container chart-container-tall">
                          <ResponsiveContainer width="100%" height="100%">
                            <ComposedChart data={hbtResult.spread_series} margin={{ top: 12, right: 24, left: 8, bottom: 8 }}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#F0F0F0" />
                              <XAxis dataKey="ts_str" stroke="#6C757D" fontSize={10} tick={{ fill: '#6C757D' }}
                                tickFormatter={(v) => v?.slice(11, 16)} />
                              <YAxis stroke="#6C757D" fontSize={10} tick={{ fill: '#6C757D' }}
                                tickFormatter={(v) => `${v.toFixed(3)}%`} />
                              <Tooltip contentStyle={tooltipStyle}
                                formatter={(v, n) => [typeof v === 'number' ? `${v.toFixed(4)}${n === 'Spread %' ? '%' : ''}` : v, n]} />
                              <ReferenceLine y={0} stroke="#ADB5BD" strokeDasharray="4 2" />
                              <ReferenceLine y={(hbtFeeA + hbtFeeB) * 100} stroke="#DC3545" strokeDasharray="3 3" strokeWidth={1.5}
                                label={{ value: `+B/E ${beStr}`, position: 'insideTopRight', fontSize: 9, fill: '#DC3545' }} />
                              <ReferenceLine y={-(hbtFeeA + hbtFeeB) * 100} stroke="#DC3545" strokeDasharray="3 3" strokeWidth={1.5}
                                label={{ value: `-B/E`, position: 'insideBottomRight', fontSize: 9, fill: '#DC3545' }} />
                              <Area type="monotone" dataKey="spread_pct" name="Spread %" dot={false} strokeWidth={1.5}
                                stroke="#0D6EFD" fill="#DBEAFE" fillOpacity={0.35} isAnimationActive={false} />
                            </ComposedChart>
                          </ResponsiveContainer>
                        </div>
                      </div>

                      <div className="card chart-card chart-card-tall">
                        <div className="card-title">Raw Z-Score vs Adaptive Threshold — {s.zscore_window_min}-min rolling</div>
                        <p className="chart-legend-hint">
                          <strong>Trade trigger:</strong> |z-score| ≥ threshold <em>and</em> |spread| &gt; {beStr}.
                          The z-score here is the raw rolling z-score — identical to the quantity used in live mode
                          for BSDEX (volume weighting is not applied, since Bitstamp REST volumes are polled, not streamed).
                        </p>
                        <div className="chart-container chart-container-tall">
                          <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={hbtResult.spread_series} margin={{ top: 12, right: 24, left: 8, bottom: 8 }}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#F0F0F0" />
                              <XAxis dataKey="ts_str" stroke="#6C757D" fontSize={10} tick={{ fill: '#6C757D' }}
                                tickFormatter={(v) => v?.slice(11, 16)} />
                              <YAxis stroke="#6C757D" fontSize={10} tick={{ fill: '#6C757D' }} />
                              <Tooltip contentStyle={tooltipStyle} />
                              <Legend />
                              <ReferenceLine y={0} stroke="#ADB5BD" strokeDasharray="4 2" />
                              <Line type="monotone" dataKey="z_score" name="Raw Z-Score (trigger qty)" stroke="#198754"
                                dot={false} strokeWidth={2} isAnimationActive={false} connectNulls={false} />
                              <Line type="monotone" dataKey="threshold" name={`Threshold (${s.zscore_threshold}σ)`} stroke="#DC3545"
                                dot={false} strokeWidth={1.5} strokeDasharray="6 4" isAnimationActive={false} />
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      </div>
                    </section>
                  )}

                  {/* ── Trade log ────────────────────────────────────── */}
                  {hbtResult.trades?.length > 0 ? (
                    <section className="activity-section">
                      <div className="card">
                        <div className="card-title">
                          Trade Log — {hbtResult.trades.length} trade{hbtResult.trades.length !== 1 ? 's' : ''} executed
                          <button type="button" className="btn btn-secondary"
                            onClick={handleExportExcel}
                            style={{ float: 'right', fontSize: 12, padding: '3px 10px' }}>
                            Export to Excel
                          </button>
                        </div>
                        <div className="signal-table-wrap">
                          <table className="signal-table">
                            <thead>
                              <tr>
                                <th>Time (UTC)</th>
                                <th>Direction</th>
                                <th>Spread %</th>
                                <th>Z-Score</th>
                                <th>Price A (€)</th>
                                <th>Price B (€)</th>
                                <th>Amount</th>
                                <th>Gross (€)</th>
                                <th>Fees (€)</th>
                                <th>Net PnL (€)</th>
                              </tr>
                            </thead>
                            <tbody>
                              {hbtResult.trades.map((t, i) => (
                                <tr key={i}>
                                  <td style={{ fontSize: 11 }}>{t.ts_str?.slice(0, 16).replace('T', ' ')}</td>
                                  <td className="route-cell" style={{ fontSize: 11 }}>{t.direction}</td>
                                  <td className={t.spread_pct > 0 ? 'positive' : 'negative'}>{t.spread_pct?.toFixed(4)}%</td>
                                  <td>{t.z_score?.toFixed(3)}</td>
                                  <td>€{t.price_a_eur?.toFixed(2)}</td>
                                  <td>€{t.price_b_eur?.toFixed(2)}</td>
                                  <td style={{ fontSize: 11 }}>{t.amount?.toFixed(5)}</td>
                                  <td className={t.gross_eur >= 0 ? 'signal-buy' : 'signal-sell'}>€{t.gross_eur?.toFixed(4)}</td>
                                  <td className="negative">€{t.fees_eur?.toFixed(4)}</td>
                                  <td className={t.pnl_eur >= 0 ? 'signal-buy' : 'signal-sell'}>
                                    <strong>€{t.pnl_eur?.toFixed(4)}</strong>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </section>
                  ) : (
                    <section>
                      <div className="card" style={{ textAlign: 'center', padding: 36, color: '#6C757D' }}>
                        <strong>No trades executed</strong> in this period under the selected fee tier.
                        <br /><br />
                        The real historical spread between Bitstamp and Binance did not exceed the
                        break-even threshold of <strong>{((hbtFeeA + hbtFeeB) * 100).toFixed(3)}%</strong> long enough
                        to trigger the z-score signal. This is honest — real exchange fees make tight spreads unprofitable.
                        <br /><br />
                        Try a lower fee tier (e.g. &gt;$100M volume) or a different date range.
                      </div>
                    </section>
                  )}
                </>
              );
            })()}
          </div>
        )}

        {/* ══════════════════════════════════════════════════════════
             BSDEX VS WORLD TAB
            ══════════════════════════════════════════════════════════ */}
        {activeTab === 'bsdex' && (<>

        {/* ── Section 1: Market Overview ─────────────────────────── */}
        <section>
          <h2 className="section-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span>Market Overview — {bsdexMarket === 'btc-eur' ? 'BTC/EUR' : 'ETH/EUR'}</span>
            <select className="pair-select" value={bsdexMarket} onChange={(e) => setBsdexMarket(e.target.value)}>
              <option value="btc-eur">BTC/EUR</option>
              <option value="eth-eur">ETH/EUR</option>
            </select>
          </h2>
          <div className="market-overview">
            <div className="card">
              <div className="card-title">{bsdexStatus?.venue_a ?? 'Venue A — Bitstamp (EUR)'}</div>
              <div className={`card-value price-trend ${bsdexPriceTrend.venueA}`}>
                {venueAMid != null ? `€${venueAMid.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}
              </div>
              <div className="card-subvalue">
                Bid: €{bsdexMarketData?.a_bid?.toFixed(2) ?? '—'} · Ask: €{bsdexMarketData?.a_ask?.toFixed(2) ?? '—'}
              </div>
            </div>
            <div className="card">
              <div className="card-title">{bsdexStatus?.venue_b ?? 'Venue B — World (EUR)'}</div>
              <div className={`card-value price-trend ${bsdexPriceTrend.venueB}`}>
                {venueBMid != null ? `€${venueBMid.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}
              </div>
              <div className="card-subvalue">
                Bid: €{bsdexMarketData?.b_bid?.toFixed(2) ?? '—'} · Ask: €{bsdexMarketData?.b_ask?.toFixed(2) ?? '—'}
                {bsdexStatus?.fx_rate_usd_eur ? <> · FX: 1 USD = €{bsdexStatus.fx_rate_usd_eur.toFixed(5)}</> : null}
              </div>
            </div>
            <div className="card">
              <div className="card-title">EUR Spread</div>
              <div className={`card-value ${bsdexSpread != null ? (bsdexSpread >= 0 ? 'positive' : 'negative') : ''}`}>
                {bsdexSpread != null ? `${bsdexSpread >= 0 ? '+' : ''}€${bsdexSpread.toFixed(2)}` : '—'}
              </div>
              <div className={`card-subvalue ${bsdexSpreadPct != null ? (bsdexSpreadPct >= 0 ? 'positive' : 'negative') : ''}`}>
                {bsdexSpreadPct != null ? `${bsdexSpreadPct >= 0 ? '+' : ''}${bsdexSpreadPct.toFixed(4)}%` : ''}
                <span style={{ marginLeft: 6, color: '#6C757D' }}>(B/E: {bsdexBreakevenPct.toFixed(3)}%)</span>
              </div>
            </div>
            <div className="card">
              <div className="card-title">Raw Z-Score <span style={{fontSize:11,color:'#6C757D',fontWeight:400}}>(trigger quantity)</span></div>
              <div className={`zscore-display card-value ${getSignalClass(Math.abs(bsdexZScore ?? 0), bsdexThreshold ?? 1)}`}>
                {bsdexZScore != null ? bsdexZScore.toFixed(4) : '—'}
              </div>
              <div className="card-subvalue">
                Threshold: {bsdexThreshold?.toFixed(4) ?? '—'}
                {bsdexSignalTriggered && <span className="positive"> · EXECUTES</span>}
                {bsdexSignalGated && <span style={{color:'#FFC107'}}> · GATED (spread &lt; B/E)</span>}
                {bsdexSignalCooldown && <span style={{color:'#6C757D'}}> · COOLDOWN</span>}
              </div>
            </div>
          </div>
        </section>

        {/* ── Section 2: Transaction Model ────────────────────────── */}
        <section>
          <h2 className="section-header">Transaction Model — BSDEX vs World Live State</h2>
          <div className="txn-flow">
            {/* SETUP */}
            <div className="txn-box">
              <div className="txn-label setup">SETUP</div>
              <div className="txn-row"><span className="txn-key">Capital per leg</span><span className="txn-val">€{bsdexCapitalEur.toLocaleString()}</span></div>
              <div className="txn-row">
                <span className="txn-key">Implied size (A)</span>
                <span className="txn-val">{venueAMid ? `≈ ${(bsdexCapitalEur / venueAMid).toFixed(5)} ${bsdexBase}` : '—'}</span>
              </div>
              <div className="txn-row"><span className="txn-key">Venue A taker</span><span className="txn-val">{(bsdexFeeA * 100).toFixed(3)}%</span></div>
              <div className="txn-row"><span className="txn-key">Venue B taker</span><span className="txn-val">{(bsdexFeeB * 100).toFixed(3)}%</span></div>
              <div className="txn-row"><span className="txn-key">Break-even spread</span><span className="txn-val" style={{ color: '#DC3545' }}>&gt; {bsdexBreakevenPct.toFixed(3)}%</span></div>
              <div className="txn-row"><span className="txn-key">Tier</span><span className="txn-val" style={{ fontSize: 11 }}>{bsdexFeeMode === 'auto' ? bsdexVolumeTiers[bsdexTierIdx]?.label ?? '—' : 'manual'}</span></div>
            </div>

            <div className="txn-arrow">→</div>

            {/* SIGNAL DETECTED */}
            <div className="txn-box">
              <div className="txn-label signal">SIGNAL DETECTED</div>
              <div className="txn-row"><span className="txn-key">Venue A mid (EUR)</span><span className="txn-val">{venueAMid != null ? `€${venueAMid.toFixed(2)}` : '—'}</span></div>
              <div className="txn-row"><span className="txn-key">Venue B mid (EUR)</span><span className="txn-val">{venueBMid != null ? `€${venueBMid.toFixed(2)}` : '—'}</span></div>
              <div className="txn-row">
                <span className="txn-key">EUR Spread</span>
                <span className={`txn-val ${bsdexSpread != null ? (bsdexSpread > 0 ? 'positive' : bsdexSpread < 0 ? 'negative' : '') : ''}`}>
                  {bsdexSpread != null ? `${bsdexSpread >= 0 ? '+' : ''}€${bsdexSpread.toFixed(4)} (${bsdexSpreadPct?.toFixed(4)}%)` : '—'}
                </span>
              </div>
              <div className="txn-row">
                <span className="txn-key">Z-Score</span>
                <span className={`txn-val ${getSignalClass(Math.abs(bsdexZScore ?? 0), bsdexThreshold ?? 1)}`}>{bsdexZScore?.toFixed(4) ?? '—'}</span>
              </div>
              <div className="txn-row"><span className="txn-key">Threshold</span><span className="txn-val">{bsdexThreshold?.toFixed(4) ?? '—'}</span></div>
              <div className="txn-row">
                <span className="txn-key">State</span>
                <span className={`txn-val ${bsdexSignalTriggered ? 'positive' : bsdexSignalGated ? '' : ''}`}
                  style={{color: bsdexSignalTriggered ? '#28A745' : bsdexSignalGated ? '#FFC107' : bsdexSignalCooldown ? '#6C757D' : '#ADB5BD'}}>
                  {bsdexSignalTriggered ? 'SIGNAL — executing'
                    : bsdexSignalGated ? 'SIGNAL — spread too thin for fees'
                    : bsdexSignalCooldown ? 'SIGNAL — in cooldown'
                    : 'HOLD'}
                </span>
              </div>
            </div>

            <div className="txn-arrow">→</div>

            {/* SIMULTANEOUS EXECUTION */}
            <div className={`txn-box ${bsdexSignalTriggered ? 'txn-box-active' : ''}`}>
              <div className="txn-label execution">SIMULTANEOUS EXECUTION</div>
              {bsdexSignalTriggered ? (
                <>
                  {(() => {
                    const buyOnA  = (bsdexSpread ?? 0) < 0;
                    const priceA  = buyOnA ? bsdexMarketData?.a_ask : bsdexMarketData?.a_bid;
                    const priceB  = buyOnA ? bsdexMarketData?.b_bid : bsdexMarketData?.b_ask;
                    const amtA    = priceA ? (bsdexCapitalEur / priceA).toFixed(5) : '?';
                    const amtB    = priceB ? (bsdexCapitalEur / priceB).toFixed(5) : '?';
                    return buyOnA ? (
                      <>
                        <div className="txn-exec-leg buy">
                          <span className="exec-side">BUY</span> {amtA} {bsdexBase} on Venue A<br />
                          <span className="exec-price">@ €{priceA?.toFixed(2)} · cost ≈ €{priceA ? (bsdexCapitalEur * (1 + bsdexFeeA)).toFixed(2) : '?'}</span>
                        </div>
                        <div className="txn-exec-leg sell">
                          <span className="exec-side">SELL</span> {amtB} {bsdexBase} on Venue B<br />
                          <span className="exec-price">@ €{priceB?.toFixed(2)} · proceeds ≈ €{priceB ? (bsdexCapitalEur * (1 - bsdexFeeB)).toFixed(2) : '?'}</span>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="txn-exec-leg sell">
                          <span className="exec-side">SELL</span> {amtA} {bsdexBase} on Venue A<br />
                          <span className="exec-price">@ €{priceA?.toFixed(2)} · proceeds ≈ €{priceA ? (bsdexCapitalEur * (1 - bsdexFeeA)).toFixed(2) : '?'}</span>
                        </div>
                        <div className="txn-exec-leg buy">
                          <span className="exec-side">BUY</span> {amtB} {bsdexBase} on Venue B<br />
                          <span className="exec-price">@ €{priceB?.toFixed(2)} · cost ≈ €{priceB ? (bsdexCapitalEur * (1 + bsdexFeeB)).toFixed(2) : '?'}</span>
                        </div>
                      </>
                    );
                  })()}
                  <div className="txn-result">Net position: market-neutral. EUR spread captured.</div>
                </>
              ) : bsdexSignalGated ? (
                <div className="txn-waiting" style={{borderColor:'#856404',color:'#856404',background:'rgba(255,193,7,0.08)'}}>
                  <strong>Z-score threshold crossed</strong> but spread ({bsdexSpreadPct != null ? Math.abs(bsdexSpreadPct).toFixed(4) : '?'}%) is below break-even ({bsdexBreakevenPct.toFixed(3)}%). No trade — spread does not cover fees.
                </div>
              ) : bsdexSignalCooldown ? (
                <div className="txn-waiting" style={{borderColor:'#6C757D',color:'#6C757D',background:'rgba(108,117,125,0.08)'}}>
                  Signal active but within post-trade cooldown window. Waiting before next trade…
                </div>
              ) : (
                <div className="txn-waiting">
                  Waiting: |z-score| ≥ threshold <em>and</em> |spread| &gt; {bsdexBreakevenPct.toFixed(3)}% (break-even)…
                </div>
              )}
            </div>
          </div>
        </section>

        {/* ── Methodology Disclosure ──────────────────────────── */}
        <section>
          <details className="methodology-disclosure">
            <summary>Monitor Methodology &amp; Model Assumptions</summary>
            <div className="methodology-body">
              <div className="methodology-col">
                <h4>Architecture</h4>
                <p>This is a <strong>latency-tolerant statistical arbitrage monitor</strong> — not an HFT execution engine. It polls Bitstamp and Binance REST endpoints every ~1 s. The spread dislocation exploited (BSDEX/Bitstamp structural lag, lower liquidity) occurs on a seconds-to-minutes time scale, which a 1 s loop can genuinely capture.</p>
              </div>
              <div className="methodology-col">
                <h4>Signal Logic</h4>
                <p><strong>Trigger quantity:</strong> raw z-score of the EUR price spread over a rolling window. Adaptive threshold adjusts for spread volatility. Bitstamp REST volumes are polled at ~1 s intervals rather than streamed tick-by-tick, so volume weighting is not applied — the raw z-score drives both display and trade decisions, keeping the signal definition consistent with the historical backtest.</p>
              </div>
              <div className="methodology-col">
                <h4>FX Conversion</h4>
                <p>Binance USDT prices are converted to EUR via the ECB rate refreshed every 60 s from api.frankfurter.app. Intraday EUR/USD drift (typically 1–3 bp/hr) represents an unhedged basis risk on each leg.</p>
              </div>
            </div>
          </details>
        </section>

        {/* ── Section 3: Charts ───────────────────────────────────── */}
        <section className="charts-stack">
          <div className="card chart-card chart-card-tall">
            <div className="card-title">EUR Cross-Exchange Spread — {bsdexMarket.toUpperCase()}</div>
            <p className="chart-legend-hint">
              Venue A bid − Venue B ask as % of world mid-price. Positive → Venue A expensive (sell A, buy B).
              <span style={{ marginLeft: 8, color: '#DC3545' }}>
                Dashed lines = ±{bsdexBreakevenPct.toFixed(3)}% break-even (trade fires only above this).
              </span>
            </p>
            {bsdexChartData.length === 0 ? (
              <div className="skeleton skeleton-chart-tall" />
            ) : (
              <div className="chart-container chart-container-tall">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={bsdexChartData} margin={{ top: 12, right: 24, left: 8, bottom: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F0F0F0" />
                    <XAxis dataKey="time" stroke="#6C757D" fontSize={11} tick={{ fill: '#6C757D' }} />
                    <YAxis stroke="#6C757D" fontSize={11} tick={{ fill: '#6C757D' }} tickFormatter={(v) => `${v.toFixed(3)}%`} />
                    <Tooltip content={<BsdexSpreadTooltip />} />
                    <ReferenceLine y={0} stroke="#ADB5BD" strokeDasharray="4 2" label={{ value: 'Par', position: 'insideLeft', fontSize: 10, fill: '#ADB5BD' }} />
                    <ReferenceLine y={bsdexBreakevenPct} stroke="#DC3545" strokeDasharray="3 3" strokeWidth={1}
                      label={{ value: 'B/E', position: 'insideTopRight', fontSize: 9, fill: '#DC3545' }} />
                    <ReferenceLine y={-bsdexBreakevenPct} stroke="#DC3545" strokeDasharray="3 3" strokeWidth={1} />
                    <Area type="monotone" dataKey="spreadPct" name="Spread %" dot={false} strokeWidth={2}
                      stroke="#0D6EFD" fill="#DBEAFE" fillOpacity={0.4} isAnimationActive={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          <div className="card chart-card chart-card-tall">
            <div className="card-title">Signal Engine — Z-Score vs Adaptive Threshold</div>
            <p className="chart-legend-hint">Trade fires when green line (z-score) crosses the red dashed adaptive threshold.</p>
            {bsdexChartData.length === 0 ? (
              <div className="skeleton skeleton-chart-tall" />
            ) : (
              <div className="chart-container chart-container-tall">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={bsdexChartData} margin={{ top: 12, right: 24, left: 8, bottom: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F0F0F0" />
                    <XAxis dataKey="time" stroke="#6C757D" fontSize={11} tick={{ fill: '#6C757D' }} />
                    <YAxis stroke="#6C757D" fontSize={11} tick={{ fill: '#6C757D' }} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend />
                    <Line type="monotone" dataKey="zScore" name="Z-Score" stroke="#198754" dot={false} strokeWidth={2.5} isAnimationActive={false} />
                    <Line type="monotone" dataKey="threshold" name="Adaptive Threshold" stroke="#DC3545" dot={false} strokeWidth={2} strokeDasharray="6 4" isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </section>

        {/* ── Section 4: Trade Activity ────────────────────────────── */}
        <section className="activity-section">
          <div className="card">
            <div className="card-title">Trade Activity (Simulated, EUR)</div>
            <p className="chart-legend-hint">
              All prices and PnL in EUR. Fees paid this session:{' '}
              <strong>€{bsdexStatus?.total_fees_eur?.toFixed(4) ?? '0.0000'}</strong>.
              Trades only fire when |spread| &gt; break-even ({bsdexBreakevenPct.toFixed(3)}%) AND z-score ≥ threshold.
            </p>
            <div className="signal-table-wrap">
              {bsdexTrades.length === 0 ? (
                <div className="empty-state">
                  No trades yet — spread must exceed {bsdexBreakevenPct.toFixed(3)}% and z-score must reach threshold.
                </div>
              ) : (
                <table className="signal-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Market</th>
                      <th>Route</th>
                      <th>Amount</th>
                      <th>Gross (€)</th>
                      <th>Fees (€)</th>
                      <th>Net (€)</th>
                      <th>Tier</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bsdexTrades.map((t, i) => {
                      const gross = (t.pnl_eur ?? 0) + (t.fees_eur ?? 0);
                      return (
                        <tr key={i}>
                          <td style={{ fontSize: 11 }}>{t.timestamp?.slice(11, 19) ?? '—'}</td>
                          <td>{t.market?.toUpperCase()}</td>
                          <td className="route-cell">{t.buy_exchange} → {t.sell_exchange}</td>
                          <td style={{ fontSize: 11 }}>{t.amount?.toFixed(5) ?? '—'}</td>
                          <td className={gross >= 0 ? 'signal-buy' : 'signal-sell'}>{gross.toFixed(4)}</td>
                          <td className="negative">{t.fees_eur?.toFixed(4) ?? '—'}</td>
                          <td className={t.pnl_eur >= 0 ? 'signal-buy' : 'signal-sell'}>{t.pnl_eur?.toFixed(4) ?? '—'}</td>
                          <td style={{ fontSize: 10, color: '#6C757D' }}>{t.tier ?? '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </section>

        {/* ── Section 5: Fee & Capital Config + Session Stats ────── */}
        <section className="bottom-section">

          {/* Fee & Capital Configuration */}
          <div className="card config-panel">
            <div className="card-title">Fee &amp; Capital Configuration</div>

            {/* Mode toggle */}
            <div className="fee-mode-row">
              <label className="fee-mode-opt">
                <input type="radio" name="bsdexFeeMode" value="auto" checked={bsdexFeeMode === 'auto'} onChange={() => handleBsdexFeeModeChange('auto')} />
                {' '}Volume tier (auto)
              </label>
              <label className="fee-mode-opt">
                <input type="radio" name="bsdexFeeMode" value="manual" checked={bsdexFeeMode === 'manual'} onChange={() => handleBsdexFeeModeChange('manual')} />
                {' '}Manual override
              </label>
            </div>

            {/* Tier dropdown — only visible in auto mode */}
            {bsdexFeeMode === 'auto' && (
              <div className="config-field">
                <label className="config-label" htmlFor="bsdex-tier-select">30-Day USD Trading Volume</label>
                <select
                  id="bsdex-tier-select"
                  className="config-input"
                  value={bsdexTierIdx}
                  onChange={(e) => handleBsdexTierChange(parseInt(e.target.value))}
                >
                  {bsdexVolumeTiers.map((t, i) => (
                    <option key={i} value={i}>
                      {t.label} — Bitstamp: {(t.bitstamp_taker * 100).toFixed(2)}% · LMAX: {(t.lmax_taker * 100).toFixed(2)}% · B/E: {((t.bitstamp_taker + t.lmax_taker) * 100).toFixed(2)}%
                    </option>
                  ))}
                </select>
                {bsdexVolumeTiers[bsdexTierIdx]?.note && (
                  <div className="config-hint" style={{ color: '#856404' }}>{bsdexVolumeTiers[bsdexTierIdx].note}</div>
                )}
              </div>
            )}

            {/* Per-venue fee inputs */}
            <div className="fee-inputs-row">
              <div className="fee-input-group">
                <label className="config-label">Venue A — Bitstamp taker</label>
                <div className="fee-input-wrap">
                  <input
                    type="number" className="config-input fee-pct-input"
                    min="0" max="5" step="0.001"
                    value={(bsdexFeeA * 100).toFixed(3)}
                    readOnly={bsdexFeeMode === 'auto'}
                    style={bsdexFeeMode === 'auto' ? { background: '#F8F9FA', cursor: 'not-allowed' } : {}}
                    onChange={(e) => setBsdexFeeA(Math.max(0, parseFloat(e.target.value) || 0) / 100)}
                  />
                  <span className="fee-unit">%</span>
                </div>
              </div>
              <div className="fee-input-group">
                <label className="config-label">Venue B — LMAX Digital taker</label>
                <div className="fee-input-wrap">
                  <input
                    type="number" className="config-input fee-pct-input"
                    min="0" max="5" step="0.001"
                    value={(bsdexFeeB * 100).toFixed(3)}
                    readOnly={bsdexFeeMode === 'auto'}
                    style={bsdexFeeMode === 'auto' ? { background: '#F8F9FA', cursor: 'not-allowed' } : {}}
                    onChange={(e) => setBsdexFeeB(Math.max(0, parseFloat(e.target.value) || 0) / 100)}
                  />
                  <span className="fee-unit">%</span>
                </div>
              </div>
            </div>

            {/* Break-even summary */}
            <div className="breakeven-banner">
              Break-even spread: <strong>{bsdexBreakevenPct.toFixed(3)}%</strong>
              <span className="breakeven-detail">({(bsdexFeeA * 100).toFixed(3)}% + {(bsdexFeeB * 100).toFixed(3)}% combined taker)</span>
            </div>

            {/* Capital per leg */}
            <div className="config-field" style={{ marginTop: 12 }}>
              <label className="config-label" htmlFor="bsdex-capital-input">Capital per leg (EUR)</label>
              <div className="fee-input-wrap">
                <input
                  id="bsdex-capital-input"
                  type="number" className="config-input fee-pct-input"
                  min="10" step="100"
                  value={bsdexCapitalEur}
                  onChange={(e) => setBsdexCapitalEur(parseFloat(e.target.value) || 1000)}
                />
                <span className="fee-unit">EUR</span>
              </div>
              <div className="config-hint">
                Deployed per venue per trade.{' '}
                {venueAMid ? `≈ ${(bsdexCapitalEur / venueAMid).toFixed(5)} ${bsdexBase} @ Venue A current price` : ''}
              </div>
            </div>

            {/* Apply button */}
            <div className="config-actions">
              <button type="button" className="btn btn-apply" onClick={handleBsdexApplyConfig} disabled={bsdexConfigSaving}>
                {bsdexConfigSaving ? 'Applying…' : 'Apply to Strategy'}
              </button>
              {bsdexConfigApplied && <span className="config-success">✓ Applied</span>}
            </div>

            {/* Reference table — all tiers */}
            {bsdexVolumeTiers.length > 0 && (
              <details style={{ marginTop: 14 }}>
                <summary className="config-label" style={{ cursor: 'pointer' }}>Fee schedule reference (all tiers)</summary>
                <div className="fee-tier-table-wrap" style={{ marginTop: 8 }}>
                  <table className="fee-tier-table">
                    <thead>
                      <tr>
                        <th>30-Day Volume</th>
                        <th>Bitstamp taker</th>
                        <th>LMAX taker</th>
                        <th>Break-even</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bsdexVolumeTiers.map((t, i) => (
                        <tr key={i} className={i === bsdexTierIdx && bsdexFeeMode === 'auto' ? 'active-tier-row' : ''}>
                          <td>{t.label}</td>
                          <td>{(t.bitstamp_taker * 100).toFixed(2)}%</td>
                          <td>{(t.lmax_taker * 100).toFixed(2)}%</td>
                          <td>{((t.bitstamp_taker + t.lmax_taker) * 100).toFixed(2)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
          </div>

          {/* Session Stats */}
          <div className="card controls-panel">
            <div className="card-title">Session Stats — BSDEX vs World</div>
            <div className="stats-grid">
              <div className="stat-item">
                <div className="stat-label">Total Trades</div>
                <div className="stat-value">{bsdexStatus?.total_trades ?? 0}</div>
              </div>
              <div className="stat-item">
                <div className="stat-label">Signal State</div>
                <div className={`stat-value signal-state-${bsdexSignalState.toLowerCase()}`}
                  title={bsdexSignalGated ? 'Z-score threshold crossed but spread insufficient for fees' : bsdexSignalCooldown ? 'In post-trade cooldown' : ''}>
                  {bsdexSignalState === 'SIGNAL_GATED' ? 'GATED' : bsdexSignalState === 'SIGNAL_COOLDOWN' ? 'COOLDOWN' : bsdexSignalState}
                </div>
              </div>
              <div className="stat-item">
                <div className="stat-label">Cumulative PnL (€)</div>
                <div className={`stat-value ${(bsdexStatus?.total_pnl_eur ?? 0) >= 0 ? 'positive' : 'negative'}`}>
                  {bsdexStatus?.total_pnl_eur?.toFixed(4) ?? '0.0000'}
                </div>
              </div>
              <div className="stat-item">
                <div className="stat-label">Win Rate</div>
                <div className="stat-value">{bsdexStatus?.win_rate_pct?.toFixed(1) ?? '0.0'}%</div>
              </div>
              <div className="stat-item">
                <div className="stat-label">Total Fees (€)</div>
                <div className="stat-value negative">{bsdexStatus?.total_fees_eur?.toFixed(4) ?? '0.0000'}</div>
              </div>
              <div className="stat-item">
                <div className="stat-label">FX Rate (USD→EUR)</div>
                <div className="stat-value">{bsdexStatus?.fx_rate_usd_eur?.toFixed(5) ?? '—'}</div>
              </div>
              <div className="stat-item">
                <div className="stat-label">Venue A Source</div>
                <div className="stat-value" style={{ fontSize: 11 }}>{bsdexStatus?.data_source ?? '—'}</div>
              </div>
              <div className="stat-item">
                <div className="stat-label">FX Age</div>
                <div className="stat-value" style={{ fontSize: 11 }}>
                  {bsdexStatus?.fx_age_sec != null ? `${Math.round(bsdexStatus.fx_age_sec)}s` : '—'}
                </div>
              </div>
            </div>

            <div className="bsdex-honesty-footer" style={{ marginTop: 16 }}>
              <strong>Data transparency:</strong>{' '}
              Venue A = <strong>Bitstamp EUR</strong> public REST (BSDEX proxy — BSDEX API requires authentication).
              Venue B = <strong>Binance USDT → EUR</strong> via ECB/Frankfurter rate (refreshed every 60 s).
              LMAX fee model is a published institutional schedule, <em>not</em> a live LMAX connection.
              <strong> All trades are simulated only.</strong>
            </div>
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
