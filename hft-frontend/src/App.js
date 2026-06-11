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
const REFRESH_INTERVAL = 2000;

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

const tooltipStyle = {
  backgroundColor: '#161C28',
  border: '1px solid #1E2736',
  borderRadius: 0,
  boxShadow: 'none',
  padding: '6px 10px',
  fontSize: 11,
  fontFamily: "'IBM Plex Mono', monospace",
};

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

/* ── Bloomberg multi-timezone clock ──────────────────────────── */
function Clock({ label, offset }) {
  const [t, setT] = useState('');
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const utc = d.getTime() + d.getTimezoneOffset() * 60000;
      const local = new Date(utc + offset * 3600000);
      setT(local.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [offset]);
  return (
    <div className="clock-cell">
      <span className="clock-label">{label}</span>
      <span className="clock-time mono">{t}</span>
    </div>
  );
}

function AppContent() {
  const [isRunning] = useState(true);
  // currentTime is managed per-timezone by Clock components

  // Tab navigation
  const [activeTab, setActiveTab] = useState('bsdex');

  // Backtesting state
  // BSDEX Historical Backtest state
  const [hbtSymbol,      setHbtSymbol]      = useState('btc-eur');
  const [hbtStartDt,     setHbtStartDt]     = useState('');        // datetime-local string
  const [hbtEndDt,       setHbtEndDt]       = useState('');
  const [hbtFeeMode,     setHbtFeeMode]     = useState('auto');
  const [hbtTierIdx,     setHbtTierIdx]     = useState(2);          // index into bsdexVolumeTiers — "> $20M" default (P7)
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
  const [bsdexTierIdx, setBsdexTierIdx]         = useState(2);        // index into volume tiers — "> $20M" default (P7)
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
      // result now has shape: { realistic, upper_bound, meta }
      setHbtResult(result);
      setHbtStatus('done');
    } catch (err) {
      setHbtError(err?.response?.data?.detail ?? err?.message ?? 'Backtest failed');
      setHbtStatus('error');
    }
  }, [hbtSymbol, hbtStartDt, hbtEndDt, hbtFeeA, hbtFeeB, hbtCapital,
      hbtFeeMode, hbtTierIdx, bsdexVolumeTiers]);

  // Excel export via SheetJS — handles dual-scenario result shape
  const handleExportExcel = useCallback(() => {
    if (!hbtResult) return;
    import('xlsx').then((XLSX) => {
      const wb = XLSX.utils.book_new();

      const writeScenario = (scenario, label) => {
        if (!scenario) return;
        const sumRows = Object.entries(scenario.summary).map(([k, v]) => ({ Field: k, Value: v }));
        XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(sumRows), `${label} Summary`);

        if (scenario.trades?.length > 0) {
          const tradeRows = scenario.trades.map((t) => ({
            Timestamp:      t.ts_str?.slice(0, 19).replace('T', ' '),
            Direction:      t.direction,
            'Spread %':     t.spread_pct,
            'Z-Score':      t.z_score,
            'Signal A (€)': t.price_a_eur,
            'Signal B (€)': t.price_b_eur,
            'Fill A (€)':   t.fill_a_eur,
            'Fill B (€)':   t.fill_b_eur,
            'Amount':       t.amount,
            'Gross (€)':    t.gross_eur,
            'Fees (€)':     t.fees_eur,
            'Net PnL (€)':  t.pnl_eur,
            'Slip bps':     t.slip_bps,
            'Buy Exchange':  t.buy_exchange,
            'Sell Exchange': t.sell_exchange,
          }));
          XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(tradeRows), `${label} Trades`);
        }

        if (scenario.spread_series?.length > 0) {
          const spreadRows = scenario.spread_series.map((p) => ({
            Timestamp:  p.ts_str?.slice(0, 19).replace('T', ' '),
            'Spread %': p.spread_pct,
            'Z-Score':  p.z_score,
            Threshold:  p.threshold,
          }));
          XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(spreadRows), `${label} Spread`);
        }
      };

      writeScenario(hbtResult.realistic,   'Realistic');
      writeScenario(hbtResult.upper_bound, 'UpperBound');

      const sym = hbtSymbol.replace(/-/g, '').toUpperCase();
      const dateStr = hbtStartDt?.slice(0, 10) ?? 'bt';
      XLSX.writeFile(wb, `BSDEX_Backtest_${sym}_${dateStr}.xlsx`);
    });
  }, [hbtResult, hbtSymbol, hbtStartDt]);




  // isConnected: derive from BSDEX market data since we only have the BSDEX tab now
  const isConnected = isRunning && !!bsdexMarketData;


  const signalTagClass = bsdexSignalTriggered ? 'tag-green'
    : bsdexSignalGated    ? 'tag-yellow'
    : bsdexSignalCooldown ? 'tag-orange'
    : 'tag-muted';
  const signalTagText = bsdexSignalTriggered ? 'SIGNAL'
    : bsdexSignalGated    ? 'GATED'
    : bsdexSignalCooldown ? 'COOLDOWN'
    : 'HOLD';

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <div className={`dashboard${activeTab === 'backtest' ? ' tab-backtest' : ''}`}>

      {/* ══ TOP BAR ══════════════════════════════════════════════ */}
      <header className="top-bar">
        <span className="top-bar-logo">STAT ARB</span>
        <div className="top-bar-sep" />
        <div className="tab-nav">
          <button type="button" className={`tab-link ${activeTab === 'bsdex' ? 'active' : ''}`} onClick={() => setActiveTab('bsdex')}>BSDEX vs World</button>
          <button type="button" className={`tab-link ${activeTab === 'backtest' ? 'active' : ''}`} onClick={() => setActiveTab('backtest')}>Backtest</button>
        </div>
        <div className="top-bar-spacer" />
        <div className="top-bar-clocks">
          <Clock label="FRA" offset={2} />
          <Clock label="LDN" offset={1} />
          <Clock label="NYC" offset={-4} />
        </div>
        <div className="top-bar-sep" />
        <div className="top-bar-conn">
          <span className={`live-dot${isConnected ? '' : ' disconnected'}`} />
          <span className="top-bar-status mono">{isConnected ? 'LIVE' : 'DISC'}</span>
        </div>
      </header>

      {/* ══ LEFT PANEL (BSDEX only) ══════════════════════════════ */}
      <aside className="left-panel">
        {activeTab === 'bsdex' && (
          <>
            <div className="lp-section">
              <div className="section-header">Venue A — Bitstamp EUR</div>
              <div className="lp-row">
                <span className="lp-label">BID</span>
                <span className={`lp-value big ${bsdexPriceTrend.venueA === 'positive' ? 'pnl-pos' : bsdexPriceTrend.venueA === 'negative' ? 'pnl-neg' : ''}`}>
                  {bsdexMarketData?.a_bid != null ? `€${bsdexMarketData.a_bid.toFixed(2)}` : '—'}
                </span>
              </div>
              <div className="lp-row">
                <span className="lp-label">ASK</span>
                <span className="lp-value">{bsdexMarketData?.a_ask != null ? `€${bsdexMarketData.a_ask.toFixed(2)}` : '—'}</span>
              </div>
              <div className="lp-row">
                <span className="lp-label">MID</span>
                <span className="lp-value">{venueAMid != null ? `€${venueAMid.toFixed(2)}` : '—'}</span>
              </div>
            </div>
            <div className="lp-section">
              <div className="section-header">Venue B — World (LMAX)</div>
              <div className="lp-row">
                <span className="lp-label">BID</span>
                <span className={`lp-value big ${bsdexPriceTrend.venueB === 'positive' ? 'pnl-pos' : bsdexPriceTrend.venueB === 'negative' ? 'pnl-neg' : ''}`}>
                  {bsdexMarketData?.b_bid != null ? `€${bsdexMarketData.b_bid.toFixed(2)}` : '—'}
                </span>
              </div>
              <div className="lp-row">
                <span className="lp-label">ASK</span>
                <span className="lp-value">{bsdexMarketData?.b_ask != null ? `€${bsdexMarketData.b_ask.toFixed(2)}` : '—'}</span>
              </div>
              <div className="lp-row">
                <span className="lp-label">MID</span>
                <span className="lp-value">{venueBMid != null ? `€${venueBMid.toFixed(2)}` : '—'}</span>
              </div>
            </div>
            <div className="lp-section">
              <div className="section-header">Spread</div>
              <div className="lp-row">
                <span className="lp-label">EUR</span>
                <span className={`lp-value big ${bsdexSpread != null ? (bsdexSpread >= 0 ? 'pnl-pos' : 'pnl-neg') : ''}`}>
                  {bsdexSpread != null ? `${bsdexSpread >= 0 ? '+' : ''}€${bsdexSpread.toFixed(2)}` : '—'}
                </span>
              </div>
              <div className="lp-row">
                <span className="lp-label">PCT</span>
                <span className={`lp-value ${bsdexSpreadPct != null ? (bsdexSpreadPct >= 0 ? 'pnl-pos' : 'pnl-neg') : ''}`}>
                  {bsdexSpreadPct != null ? `${bsdexSpreadPct >= 0 ? '+' : ''}${bsdexSpreadPct.toFixed(4)}%` : '—'}
                </span>
              </div>
              <div className="lp-row">
                <span className="lp-label" style={{color:'var(--text-muted)'}}>B/E</span>
                <span className="lp-value muted">{bsdexBreakevenPct.toFixed(3)}%</span>
              </div>
            </div>
            <div className="lp-section">
              <div className="section-header">Signal</div>
              <div className="lp-row">
                <span className="lp-label">Z-SCORE</span>
                <span className={`lp-value big ${bsdexSignalTriggered ? 'pnl-pos' : ''}`}>
                  {bsdexZScore != null ? bsdexZScore.toFixed(4) : '—'}
                </span>
              </div>
              <div className="lp-row">
                <span className="lp-label">THRESHOLD</span>
                <span className="lp-value">{bsdexThreshold?.toFixed(4) ?? '—'}</span>
              </div>
              <div className="lp-row" style={{marginTop:4}}>
                <span className="lp-label">STATE</span>
                <span className={`tag ${signalTagClass}`}>{signalTagText}</span>
              </div>
            </div>
            <div className="lp-section">
              <div className="section-header">Data</div>
              <div className="lp-row">
                <span className="lp-label">FX RATE</span>
                <span className="lp-value orange">{bsdexStatus?.fx_rate_usd_eur?.toFixed(5) ?? '—'}</span>
              </div>
              <div className="lp-row">
                <span className="lp-label">FX AGE</span>
                <span className={`lp-value ${(bsdexStatus?.fx_age_sec ?? 0) > 120 ? 'pnl-neg' : ''}`}>
                  {bsdexStatus?.fx_age_sec != null ? `${Math.round(bsdexStatus.fx_age_sec)}s` : '—'}
                </span>
              </div>
              <div className="lp-row">
                <span className="lp-label">B SRC</span>
                <span className="lp-value muted" style={{fontSize:'var(--font-size-xs)'}}>
                  {bsdexMarketData?.venue_b_source === 'binance_ws_depth' ? 'WS' : 'REST'}
                </span>
              </div>
              <div className="lp-row">
                <span className="lp-label">MODEL</span>
                <span className="lp-value muted" style={{fontSize:'var(--font-size-xs)'}}>
                  {bsdexMarketData?.price_model ?? '—'}
                </span>
              </div>
            </div>
          </>
        )}
      </aside>

      {/* ══ CENTER PANEL ═════════════════════════════════════════ */}
      <div className="center-panel">

        {/* --- BSDEX vs WORLD center --- */}
        {activeTab === 'bsdex' && (
          <>
            <div className="chart-panel">
              <div className="chart-panel-header">
                <span className="chart-panel-title">Cross-Exchange Spread — {bsdexBase}-EUR</span>
                <div style={{display:'flex',alignItems:'center',gap:8}}>
                  <span className="chart-panel-sub">Bitstamp EUR vs Binance→EUR</span>
                  <select className="pair-select" value={bsdexMarket} onChange={(e) => setBsdexMarket(e.target.value)}>
                    <option value="btc-eur">BTC/EUR</option>
                    <option value="eth-eur">ETH/EUR</option>
                  </select>
                </div>
              </div>
              <div className="chart-body">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={bsdexChartData} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
                    <CartesianGrid stroke="#1E2736" strokeDasharray="3 3" />
                    <XAxis dataKey="time" tick={{ fill: '#6B7B8D', fontSize: 10, fontFamily: 'IBM Plex Mono' }}
                      axisLine={{ stroke: '#1E2736' }} tickLine={{ stroke: '#1E2736' }} />
                    <YAxis tick={{ fill: '#6B7B8D', fontSize: 10, fontFamily: 'IBM Plex Mono' }}
                      axisLine={{ stroke: '#1E2736' }} tickLine={{ stroke: '#1E2736' }}
                      tickFormatter={(v) => `${v.toFixed(3)}%`} />
                    <Tooltip content={<BsdexSpreadTooltip />} />
                    <ReferenceLine y={0} stroke="#3D4F63" strokeWidth={0.5} />
                    <ReferenceLine y={bsdexBreakevenPct} stroke="#FF8C00" strokeDasharray="4 4"
                      label={{ value: 'B/E', fill: '#FF8C00', fontSize: 9 }} />
                    <ReferenceLine y={-bsdexBreakevenPct} stroke="#FF8C00" strokeDasharray="4 4" />
                    <Area type="monotone" dataKey="spreadPct" name="Spread %" dot={false} strokeWidth={1.5}
                      stroke="#4FC3F7" fill="rgba(79,195,247,0.08)" isAnimationActive={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="chart-panel-secondary">
              <div className="chart-panel-header">
                <span className="chart-panel-title">Z-Score vs Adaptive Threshold</span>
                <span className="chart-panel-sub">trade fires when z ≥ threshold &amp; spread &gt; B/E</span>
              </div>
              <div className="chart-body">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={bsdexChartData} margin={{ top: 4, right: 16, left: 4, bottom: 4 }}>
                    <CartesianGrid stroke="#1E2736" strokeDasharray="3 3" />
                    <XAxis dataKey="time" tick={{ fill: '#6B7B8D', fontSize: 9, fontFamily: 'IBM Plex Mono' }}
                      axisLine={{ stroke: '#1E2736' }} tickLine={{ stroke: '#1E2736' }} />
                    <YAxis tick={{ fill: '#6B7B8D', fontSize: 9, fontFamily: 'IBM Plex Mono' }}
                      axisLine={{ stroke: '#1E2736' }} tickLine={{ stroke: '#1E2736' }} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <ReferenceLine y={0} stroke="#3D4F63" strokeWidth={0.5} />
                    <Line type="monotone" dataKey="zScore" name="Z-Score" stroke="#00B060" dot={false} strokeWidth={1.5} isAnimationActive={false} />
                    <Line type="monotone" dataKey="threshold" name="Threshold" stroke="#FF3B3B" dot={false} strokeWidth={1} strokeDasharray="6 4" isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="txn-model">
              <div className="txn-box">
                <div className="txn-title setup">Setup</div>
                <div className="txn-row"><span className="txn-key">Capital</span><span className="txn-val">€{bsdexCapitalEur.toLocaleString()}</span></div>
                <div className="txn-row"><span className="txn-key">B/E</span><span className="txn-val">{bsdexBreakevenPct.toFixed(3)}%</span></div>
                <div className="txn-row"><span className="txn-key">Fee A</span><span className="txn-val">{(bsdexFeeA*100).toFixed(3)}%</span></div>
                <div className="txn-row"><span className="txn-key">Fee B</span><span className="txn-val">{(bsdexFeeB*100).toFixed(3)}%</span></div>
              </div>
              <div className="txn-arrow">›</div>
              <div className="txn-box">
                <div className="txn-title signal">Signal</div>
                <div className="txn-row"><span className="txn-key">Z-Score</span><span className="txn-val">{bsdexZScore?.toFixed(4) ?? '—'}</span></div>
                <div className="txn-row"><span className="txn-key">Threshold</span><span className="txn-val">{bsdexThreshold?.toFixed(4) ?? '—'}</span></div>
                <div className="txn-row"><span className="txn-key">Spread</span><span className={`txn-val ${bsdexSpreadPct != null ? (bsdexSpreadPct >= 0 ? 'pnl-pos' : 'pnl-neg') : ''}`}>{bsdexSpreadPct?.toFixed(4) ?? '—'}%</span></div>
              </div>
              <div className="txn-arrow">›</div>
              <div className={`txn-box ${bsdexSignalTriggered ? 'active-box' : bsdexSignalGated ? 'gated-box' : ''}`}>
                <div className={`txn-title ${bsdexSignalTriggered ? 'exec' : bsdexSignalGated ? 'gated' : 'signal'}`}>
                  {bsdexSignalTriggered ? 'Execution' : bsdexSignalGated ? 'Gated' : 'Waiting'}
                </div>
                {bsdexSignalTriggered ? (
                  <>
                    <div className="exec-leg buy">BUY {bsdexStatus?.venue_b ?? 'World'} <span className="exec-price">{bsdexMarketData?.b_ask?.toFixed(2)}</span></div>
                    <div className="exec-leg sell">SELL {bsdexStatus?.venue_a ?? 'Bitstamp'} <span className="exec-price">{bsdexMarketData?.a_bid?.toFixed(2)}</span></div>
                  </>
                ) : bsdexSignalGated ? (
                  <div className="txn-waiting">Spread {bsdexSpreadPct?.toFixed(4)}% &lt; B/E {bsdexBreakevenPct.toFixed(3)}%</div>
                ) : bsdexSignalCooldown ? (
                  <div className="txn-waiting">Post-trade cooldown active</div>
                ) : (
                  <div className="txn-waiting">Waiting for z ≥ threshold</div>
                )}
              </div>
            </div>
            <details className="methodology-disclosure">
              <summary>Monitor Methodology &amp; Model Assumptions</summary>
              <div className="methodology-body">
                <div className="methodology-col">
                  <h4>Architecture</h4>
                  <p>Latency-tolerant statistical arbitrage monitor. Polls Bitstamp and Binance REST every ~1 s. The spread dislocation (BSDEX/Bitstamp structural lag, lower liquidity) occurs on a seconds-to-minutes time scale, which a 1 s loop genuinely captures.</p>
                </div>
                <div className="methodology-col">
                  <h4>Signal Logic</h4>
                  <p><strong>Trigger quantity:</strong> raw z-score of the EUR price spread over a rolling window. Adaptive threshold adjusts for spread volatility. Raw z-score drives both display and trade decisions — consistent with the historical backtest.</p>
                </div>
                <div className="methodology-col">
                  <h4>FX Conversion</h4>
                  <p>Binance USDT prices converted to EUR via ECB rate refreshed every 60 s from api.frankfurter.app. Intraday EUR/USD drift (1–3 bp/hr) represents an unhedged basis risk on each leg.</p>
                </div>
              </div>
            </details>
          </>
        )}

        {/* --- BACKTEST center --- */}
        {activeTab === 'backtest' && (
          <div className="backtest-layout">
            <div className="bt-config-panel">
              <div className="section-header">BSDEX vs World — Historical Backtest</div>
              <p style={{fontSize:'var(--font-size-xs)',color:'var(--text-secondary)',margin:'0 0 10px',lineHeight:1.6}}>
                Fetches <strong>real 1-minute OHLCV</strong> from Bitstamp (EUR) and Binance (USDT→EUR via Frankfurter/ECB FX).
                Runs the same spread / z-score logic as the live strategy (60-min rolling window, threshold 1.5σ, 30-min trade cooldown).
                All prices and PnL in <strong>EUR</strong>. Max range: 7 days.
              </p>
              <div className="bt-config-grid">
                <div className="bt-field">
                  <label>Market</label>
                  <select className="bb-select" value={hbtSymbol} onChange={(e) => setHbtSymbol(e.target.value)}>
                    <option value="btc-eur">BTC/EUR (Bitstamp vs Binance→EUR)</option>
                    <option value="eth-eur">ETH/EUR (Bitstamp vs Binance→EUR)</option>
                    <option value="btc-eur-kraken">Control pair (no FX leg) — BTC/EUR Bitstamp vs Kraken</option>
                  </select>
                </div>
                <div className="bt-field">
                  <label>Start (UTC)</label>
                  <input type="datetime-local" className="bb-input" value={hbtStartDt} onChange={(e) => setHbtStartDt(e.target.value)} />
                </div>
                <div className="bt-field">
                  <label>End (UTC)</label>
                  <input type="datetime-local" className="bb-input" value={hbtEndDt} onChange={(e) => setHbtEndDt(e.target.value)} />
                </div>
                <div className="bt-field">
                  <label>Capital / leg (EUR)</label>
                  <input type="number" className="bb-input" min="10" step="100" value={hbtCapital}
                    onChange={(e) => setHbtCapital(parseFloat(e.target.value) || 1000)} />
                </div>
              </div>
              <div className="bt-fee-row">
                <div className="fee-mode-toggle" style={{width:180,flexShrink:0}}>
                  <button className={`fee-mode-btn ${hbtFeeMode === 'auto' ? 'active' : ''}`} onClick={() => handleHbtFeeModeChange('auto')}>Auto</button>
                  <button className={`fee-mode-btn ${hbtFeeMode === 'manual' ? 'active' : ''}`} onClick={() => handleHbtFeeModeChange('manual')}>Manual</button>
                </div>
                {hbtFeeMode === 'auto' && (
                  <div className="bt-field" style={{flex:1}}>
                    <label>Volume Tier</label>
                    <select className="bb-select" value={hbtTierIdx} onChange={(e) => handleHbtTierChange(parseInt(e.target.value))}>
                      {bsdexVolumeTiers.map((t, i) => (
                        <option key={i} value={i}>{t.label} — BS:{(t.bitstamp_taker*100).toFixed(2)}% · LM:{(t.lmax_taker*100).toFixed(2)}% · B/E:{((t.bitstamp_taker+t.lmax_taker)*100).toFixed(2)}%</option>
                      ))}
                    </select>
                  </div>
                )}
                <div className="bt-field" style={{width:120,flexShrink:0}}>
                  <label>Venue A Taker %</label>
                  <input type="number" className="bb-input" min="0" max="5" step="0.001"
                    value={(hbtFeeA*100).toFixed(3)} readOnly={hbtFeeMode === 'auto'}
                    onChange={(e) => setHbtFeeA(Math.max(0, parseFloat(e.target.value)||0)/100)} />
                </div>
                <div className="bt-field" style={{width:120,flexShrink:0}}>
                  <label>Venue B Taker %</label>
                  <input type="number" className="bb-input" min="0" max="5" step="0.001"
                    value={(hbtFeeB*100).toFixed(3)} readOnly={hbtFeeMode === 'auto'}
                    onChange={(e) => setHbtFeeB(Math.max(0, parseFloat(e.target.value)||0)/100)} />
                </div>
              </div>
              <div className="be-box" style={{width:'fit-content',marginBottom:8}}>
                <span className="be-label">B/E Spread</span>
                <span className="be-value" style={{marginLeft:12}}>{((hbtFeeA+hbtFeeB)*100).toFixed(3)}%</span>
              </div>
              <div className="bt-actions">
                <button type="button" className="bb-btn" onClick={handleRunHistoricalBacktest} disabled={hbtStatus === 'running'}>
                  {hbtStatus === 'running' ? 'Fetching…' : 'Run Backtest'}
                </button>
                {hbtResult && hbtStatus === 'done' && (
                  <button type="button" className="bb-btn-secondary" onClick={handleExportExcel}>Export Excel</button>
                )}
                {hbtStatus === 'running' && <span className="spinner" />}
                {hbtError && <span className="bt-error">{hbtError}</span>}
              </div>
            </div>

            {hbtStatus === 'running' && (
              <div style={{background:'var(--bg-panel)',border:'1px solid var(--border)',padding:24,textAlign:'center'}}>
                <div style={{fontSize:'var(--font-size-sm)',color:'var(--text-secondary)'}}>Fetching real 1-minute OHLCV from Bitstamp &amp; Binance…</div>
                <div style={{marginTop:8,fontSize:'var(--font-size-xs)',color:'var(--text-muted)'}}>Depending on date range this takes 5–30 seconds (live API calls).</div>
              </div>
            )}

            {hbtResult && hbtStatus === 'done' && (() => {
              // P6: dual-scenario result shape { realistic, upper_bound, meta }
              const real = hbtResult.realistic;
              const ub   = hbtResult.upper_bound;
              const meta = hbtResult.meta ?? {};
              if (!real) return null;

              const rs = real.summary;
              const us = ub?.summary;
              const netPos = rs.total_pnl_eur >= 0;
              const beStr  = `${rs.breakeven_spread_pct?.toFixed(3)}%`;
              const fxTag  = meta.fx_granularity === '1m' ? '1m intraday' : meta.fx_granularity === 'none-eur-native' ? 'native EUR' : 'daily fallback ⚠';
              const ec     = rs.exec_costs ?? {};

              const kpiCard = (label, val, cls) => (
                <div className="bt-kpi-cell" key={label}>
                  <div className="bt-kpi-label">{label}</div>
                  <div className={`bt-kpi-value ${cls}`}>{val ?? '—'}</div>
                </div>
              );

              return (
                <div className="bt-results">

                  {/* ── Scenario banner ──────────────────────────────── */}
                  <div style={{background:'var(--bg-panel)',border:'1px solid var(--border)',padding:'6px 12px',marginBottom:8,fontSize:'var(--font-size-xs)',color:'var(--text-secondary)',display:'flex',gap:16,flexWrap:'wrap',alignItems:'center'}}>
                    <span><strong style={{color:'var(--text-primary)'}}>Tier:</strong> {rs.tier_label}</span>
                    <span><strong style={{color:'var(--text-primary)'}}>FX:</strong> {fxTag}</span>
                    <span><strong style={{color:'var(--text-primary)'}}>Half-spread:</strong> A={ec.half_spread_bps_venue_a} bps · B={ec.half_spread_bps_venue_b} bps</span>
                    <span><strong style={{color:'var(--text-primary)'}}>Slippage:</strong> {ec.slippage_bps} bps</span>
                    <span style={{marginLeft:'auto',color:'var(--text-muted)'}}>Fills: bar i+1 (1-min lag) · No look-ahead</span>
                  </div>

                  {/* ── REALISTIC headline KPI row ───────────────────── */}
                  <div style={{marginBottom:4,fontSize:'var(--font-size-xs)',color:'#4FC3F7',fontWeight:600,letterSpacing:'0.06em'}}>REALISTIC (bid-ask + slippage costs applied)</div>
                  <div className="bt-kpi-row" style={{marginBottom:10}}>
                    {[
                      ['Gross PnL',    `€${rs.gross_pnl_eur?.toFixed(4)}`,   rs.gross_pnl_eur >= 0 ? 'pnl-pos' : 'pnl-neg'],
                      ['Total Fees',   `−€${rs.total_fees_eur?.toFixed(4)}`,  'pnl-neg'],
                      ['Net PnL',      `€${rs.total_pnl_eur?.toFixed(4)}`,    netPos ? 'pnl-pos' : 'pnl-neg'],
                      ['Total Trades', rs.total_trades,                        ''],
                      ['Wins / Losses',`${rs.win_trades} / ${rs.loss_trades}`, ''],
                      ['Win Rate',     `${rs.win_rate_pct?.toFixed(1)}%`,      rs.win_rate_pct < 100 ? '' : 'pnl-neg'],
                      ['Max Drawdown', `€${rs.max_drawdown_eur?.toFixed(4)}`,  'pnl-neg'],
                      ['Sharpe (daily, ann.)', rs.sharpe_daily_ann != null ? rs.sharpe_daily_ann.toFixed(3) : 'n/a', ''],
                    ].map(([label, val, cls]) => kpiCard(label, val, cls))}
                  </div>

                  {/* ── UPPER BOUND secondary row ────────────────────── */}
                  {us && (
                    <>
                      <div style={{marginBottom:4,fontSize:'var(--font-size-xs)',color:'#6B7B8D',fontWeight:600,letterSpacing:'0.06em'}}>UPPER BOUND (mid-price fills — theoretical maximum, no exec costs)</div>
                      <div className="bt-kpi-row" style={{marginBottom:14,opacity:0.75}}>
                        {[
                          ['Gross PnL',    `€${us.gross_pnl_eur?.toFixed(4)}`,  us.gross_pnl_eur >= 0 ? 'pnl-pos' : 'pnl-neg'],
                          ['Total Fees',   `−€${us.total_fees_eur?.toFixed(4)}`, 'pnl-neg'],
                          ['Net PnL',      `€${us.total_pnl_eur?.toFixed(4)}`,   us.total_pnl_eur >= 0 ? 'pnl-pos' : 'pnl-neg'],
                          ['Total Trades', us.total_trades,                       ''],
                          ['Wins / Losses',`${us.win_trades} / ${us.loss_trades}`,''],
                          ['Win Rate',     `${us.win_rate_pct?.toFixed(1)}%`,     ''],
                          ['Max Drawdown', `€${us.max_drawdown_eur?.toFixed(4)}`, 'pnl-neg'],
                          ['Sharpe (daily, ann.)', us.sharpe_daily_ann != null ? us.sharpe_daily_ann.toFixed(3) : 'n/a', ''],
                        ].map(([label, val, cls]) => kpiCard(label, val, cls))}
                      </div>
                    </>
                  )}

                  {/* ── Charts (realistic scenario) ──────────────────── */}
                  {real.equity_curve?.length > 1 && (
                    <div className="bt-chart-grid">
                      <div className="bt-chart-box">
                        <div className="bt-chart-title">Cumulative Net PnL — Realistic (EUR)</div>
                        <ResponsiveContainer width="100%" height={200}>
                          <ComposedChart data={real.equity_curve} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
                            <CartesianGrid stroke="#1E2736" strokeDasharray="3 3" />
                            <XAxis dataKey="ts_str" tick={{ fill: '#6B7B8D', fontSize: 9, fontFamily: 'IBM Plex Mono' }}
                              axisLine={{ stroke: '#1E2736' }} tickLine={{ stroke: '#1E2736' }}
                              tickFormatter={(v) => v?.slice(11,16)} />
                            <YAxis tick={{ fill: '#6B7B8D', fontSize: 9, fontFamily: 'IBM Plex Mono' }}
                              axisLine={{ stroke: '#1E2736' }} tickLine={{ stroke: '#1E2736' }}
                              tickFormatter={(v) => `€${v.toFixed(2)}`} />
                            <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`€${v.toFixed(4)}`, 'Net PnL']} />
                            <ReferenceLine y={0} stroke="#3D4F63" strokeWidth={0.5} />
                            <Area type="monotone" dataKey="cumulative_pnl" name="Net PnL (€)"
                              stroke={netPos ? '#00B060' : '#FF3B3B'} fill={netPos ? 'rgba(0,176,96,0.08)' : 'rgba(255,59,59,0.08)'}
                              strokeWidth={1.5} dot={false} isAnimationActive={false} />
                          </ComposedChart>
                        </ResponsiveContainer>
                      </div>
                      {real.spread_series?.length > 1 && (
                        <div className="bt-chart-box">
                          <div className="bt-chart-title">Historical Spread % — {rs.bitstamp_symbol} vs {rs.world_symbol}</div>
                          <ResponsiveContainer width="100%" height={200}>
                            <ComposedChart data={real.spread_series} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
                              <CartesianGrid stroke="#1E2736" strokeDasharray="3 3" />
                              <XAxis dataKey="ts_str" tick={{ fill: '#6B7B8D', fontSize: 9, fontFamily: 'IBM Plex Mono' }}
                                axisLine={{ stroke: '#1E2736' }} tickLine={{ stroke: '#1E2736' }}
                                tickFormatter={(v) => v?.slice(11,16)} />
                              <YAxis tick={{ fill: '#6B7B8D', fontSize: 9, fontFamily: 'IBM Plex Mono' }}
                                axisLine={{ stroke: '#1E2736' }} tickLine={{ stroke: '#1E2736' }}
                                tickFormatter={(v) => `${v.toFixed(3)}%`} />
                              <Tooltip contentStyle={tooltipStyle} />
                              <ReferenceLine y={0} stroke="#3D4F63" strokeWidth={0.5} />
                              <ReferenceLine y={(hbtFeeA+hbtFeeB)*100} stroke="#FF8C00" strokeDasharray="4 4"
                                label={{ value: `B/E ${beStr}`, fill: '#FF8C00', fontSize: 9 }} />
                              <ReferenceLine y={-(hbtFeeA+hbtFeeB)*100} stroke="#FF8C00" strokeDasharray="4 4" />
                              <Area type="monotone" dataKey="spread_pct" name="Spread %" dot={false} strokeWidth={1.5}
                                stroke="#4FC3F7" fill="rgba(79,195,247,0.08)" isAnimationActive={false} />
                            </ComposedChart>
                          </ResponsiveContainer>
                        </div>
                      )}
                    </div>
                  )}
                  {real.spread_series?.length > 1 && (
                    <div className="bt-chart-box">
                      <div className="bt-chart-title">Raw Z-Score vs Threshold — {rs.zscore_window_min}-min rolling</div>
                      <ResponsiveContainer width="100%" height={180}>
                        <LineChart data={real.spread_series} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
                          <CartesianGrid stroke="#1E2736" strokeDasharray="3 3" />
                          <XAxis dataKey="ts_str" tick={{ fill: '#6B7B8D', fontSize: 9, fontFamily: 'IBM Plex Mono' }}
                            axisLine={{ stroke: '#1E2736' }} tickLine={{ stroke: '#1E2736' }}
                            tickFormatter={(v) => v?.slice(11,16)} />
                          <YAxis tick={{ fill: '#6B7B8D', fontSize: 9, fontFamily: 'IBM Plex Mono' }}
                            axisLine={{ stroke: '#1E2736' }} tickLine={{ stroke: '#1E2736' }} />
                          <Tooltip contentStyle={tooltipStyle} />
                          <Legend iconSize={10} wrapperStyle={{ fontSize:10, color:'#6B7B8D' }} />
                          <ReferenceLine y={0} stroke="#3D4F63" strokeWidth={0.5} />
                          <Line type="monotone" dataKey="z_score" name="Raw Z-Score" stroke="#00B060" dot={false} strokeWidth={1.5} isAnimationActive={false} />
                          <Line type="monotone" dataKey="threshold" name={`Threshold (${rs.zscore_threshold}σ)`} stroke="#FF3B3B" dot={false} strokeWidth={1} strokeDasharray="6 4" isAnimationActive={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  )}

                  {/* ── Parameters table ─────────────────────────────── */}
                  <div className="bt-param-table">
                    <div className="section-header">Strategy Parameters &amp; Execution Model</div>
                    <table className="param-table">
                      <thead><tr><th>Parameter</th><th>Value</th><th>Note</th></tr></thead>
                      <tbody>
                        <tr><td>Scenario shown</td><td>Realistic (headline) + Upper bound (secondary)</td><td>Never present upper bound alone</td></tr>
                        <tr><td>Signal threshold</td><td>{rs.zscore_threshold}σ rolling z-score</td><td>60-min window</td></tr>
                        <tr><td>Execution</td><td>Bar i+1 fills (1-min lag)</td><td>P2: no look-ahead bias</td></tr>
                        <tr><td>Exec costs (realistic)</td><td>HS A={ec.half_spread_bps_venue_a} bps · HS B={ec.half_spread_bps_venue_b} bps · Slip {ec.slippage_bps} bps</td><td>Mid→executable price adjustment</td></tr>
                        <tr><td>Break-even gate</td><td>{rs.breakeven_spread_pct?.toFixed(3)}%</td><td>Applied to adjusted prices</td></tr>
                        <tr><td>Cooldown</td><td>{rs.trade_cooldown_min} min</td><td>Toxic flow guard</td></tr>
                        <tr><td>FX</td><td>{fxTag}</td><td>Binance EURUSDT 1m primary; daily ECB fallback</td></tr>
                        <tr><td>Tier</td><td>{rs.tier_label}</td><td>P7: >&nbsp;$20M default; >&nbsp;$1B aspirational</td></tr>
                        <tr><td>Data</td><td colSpan={2}>{rs.data_sources}</td></tr>
                      </tbody>
                    </table>
                  </div>

                  {/* ── Trade log (realistic) ────────────────────────── */}
                  {real.trades?.length > 0 ? (
                    <div style={{background:'var(--bg-panel)',border:'1px solid var(--border)'}}>
                      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'6px 10px',borderBottom:'1px solid var(--border)'}}>
                        <span className="section-header" style={{margin:0,border:'none',paddingBottom:0}}>
                          Trade Log — Realistic — {real.trades.length} trade{real.trades.length!==1?'s':''}
                        </span>
                        <button type="button" className="bb-btn-secondary" onClick={handleExportExcel}>Export Excel</button>
                      </div>
                      <div style={{overflowX:'auto'}}>
                        <table className="dense-table">
                          <thead>
                            <tr>
                              <th>Time (UTC)</th><th>Direction</th><th>Spread %</th><th>Z-Score</th>
                              <th className="right">Fill A (€)</th><th className="right">Fill B (€)</th>
                              <th className="right">Slip bps</th><th className="right">Amount</th>
                              <th className="right">Gross (€)</th><th className="right">Fees (€)</th>
                              <th className="right">Net PnL (€)</th>
                            </tr>
                          </thead>
                          <tbody>
                            {real.trades.map((t, i) => (
                              <tr key={i}>
                                <td style={{color:'var(--text-muted)'}}>{t.ts_str?.slice(0,16).replace('T',' ')}</td>
                                <td className="text">{t.direction}</td>
                                <td className={t.spread_pct > 0 ? 'pnl-pos' : 'pnl-neg'}>{t.spread_pct?.toFixed(4)}%</td>
                                <td>{t.z_score?.toFixed(3)}</td>
                                <td className="right">€{t.fill_a_eur?.toFixed(2)}</td>
                                <td className="right">€{t.fill_b_eur?.toFixed(2)}</td>
                                <td className="right" style={{color:'var(--text-muted)'}}>{t.slip_bps?.toFixed(2)}</td>
                                <td className="right">{t.amount?.toFixed(5)}</td>
                                <td className={`right ${t.gross_eur >= 0 ? 'pnl-pos' : 'pnl-neg'}`}>€{t.gross_eur?.toFixed(4)}</td>
                                <td className="right pnl-neg">€{t.fees_eur?.toFixed(4)}</td>
                                <td className={`right ${t.pnl_eur >= 0 ? 'pnl-pos' : 'pnl-neg'}`}><strong>€{t.pnl_eur?.toFixed(4)}</strong></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ) : (
                    <div style={{background:'var(--bg-panel)',border:'1px solid var(--border)',padding:24,textAlign:'center',color:'var(--text-secondary)',fontSize:'var(--font-size-sm)'}}>
                      <strong>No trades executed</strong> in this period under the selected fee tier.
                      The executable spread (after half-spread + slippage) did not exceed the break-even threshold of <strong>{beStr}</strong>.
                      Try a lower fee tier, wider date range, or check the upper-bound row for mid-price signal count.
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        )}
      </div>

      {/* ══ RIGHT PANEL (BSDEX only) ══════════════════════════════ */}
      <aside className="right-panel">
        {activeTab === 'bsdex' && (
          <>
            <div className="rp-section">
              <div className="section-header">Session Stats</div>
              <div className="rp-row"><span className="rp-label">Total Trades</span><span className="rp-value">{bsdexStatus?.total_trades ?? 0}</span></div>
              <div className="rp-row"><span className="rp-label">Win Rate</span><span className={`rp-value ${(bsdexStatus?.win_rate_pct ?? 0) >= 50 ? 'pnl-pos' : ''}`}>{bsdexStatus?.win_rate_pct?.toFixed(1) ?? '0.0'}%</span></div>
              <div className="rp-row">
                <span className="rp-label">Cum. PnL (€)</span>
                <span className={`rp-value ${(bsdexStatus?.total_pnl_eur ?? 0) >= 0 ? 'pnl-pos' : 'pnl-neg'}`}>
                  {(bsdexStatus?.total_pnl_eur ?? 0) >= 0 ? '+' : ''}{bsdexStatus?.total_pnl_eur?.toFixed(4) ?? '0.0000'}
                </span>
              </div>
              <div className="rp-row"><span className="rp-label">Total Fees (€)</span><span className="rp-value pnl-neg">{bsdexStatus?.total_fees_eur?.toFixed(4) ?? '0.0000'}</span></div>
              <div className="rp-row" style={{marginTop:4}}>
                <span className="rp-label">Signal State</span>
                <span className={`tag ${signalTagClass}`}>{signalTagText}</span>
              </div>
            </div>
            <div className="rp-section">
              <div className="section-header">Fee Configuration</div>
              <div className="fee-grid">
                <div className="fee-mode-toggle">
                  <button className={`fee-mode-btn ${bsdexFeeMode === 'auto' ? 'active' : ''}`} onClick={() => handleBsdexFeeModeChange('auto')}>Auto</button>
                  <button className={`fee-mode-btn ${bsdexFeeMode === 'manual' ? 'active' : ''}`} onClick={() => handleBsdexFeeModeChange('manual')}>Manual</button>
                </div>
                {bsdexFeeMode === 'auto' && (
                  <div className="fee-field">
                    <label>Volume Tier</label>
                    <select className="bb-select" value={bsdexTierIdx} onChange={(e) => handleBsdexTierChange(parseInt(e.target.value))}>
                      {bsdexVolumeTiers.map((t, i) => (
                        <option key={i} value={i}>{t.label} — BS:{(t.bitstamp_taker*100).toFixed(2)}% LM:{(t.lmax_taker*100).toFixed(2)}%</option>
                      ))}
                    </select>
                  </div>
                )}
                <div className="fee-field">
                  <label>Venue A Taker</label>
                  <div className="fee-input-row">
                    <input type="number" className="bb-input" min="0" max="5" step="0.001"
                      value={(bsdexFeeA*100).toFixed(3)} readOnly={bsdexFeeMode === 'auto'}
                      onChange={(e) => setBsdexFeeA(Math.max(0, parseFloat(e.target.value)||0)/100)} />
                    <span className="fee-unit-label">%</span>
                  </div>
                </div>
                <div className="fee-field">
                  <label>Venue B Taker</label>
                  <div className="fee-input-row">
                    <input type="number" className="bb-input" min="0" max="5" step="0.001"
                      value={(bsdexFeeB*100).toFixed(3)} readOnly={bsdexFeeMode === 'auto'}
                      onChange={(e) => setBsdexFeeB(Math.max(0, parseFloat(e.target.value)||0)/100)} />
                    <span className="fee-unit-label">%</span>
                  </div>
                </div>
                <div className="be-box">
                  <span className="be-label">B/E Spread</span>
                  <span className="be-value">{bsdexBreakevenPct.toFixed(3)}%</span>
                </div>
                <div className="fee-field">
                  <label>Capital (EUR)</label>
                  <input type="number" className="bb-input" min="100" step="1000" value={bsdexCapitalEur}
                    onChange={(e) => setBsdexCapitalEur(parseFloat(e.target.value) || 1000)} />
                </div>
                <div className="config-apply-row">
                  <button type="button" className="bb-btn" onClick={handleBsdexApplyConfig} disabled={bsdexConfigSaving}>
                    {bsdexConfigSaving ? '…' : 'Apply'}
                  </button>
                  {bsdexConfigApplied && <span className="config-ok">✓ Applied</span>}
                </div>
              </div>
            </div>
          </>
        )}
      </aside>

      {/* ══ BLOTTER (BSDEX only) ═════════════════════════════════ */}
      <div className="blotter">
        {activeTab === 'bsdex' && (
          <>
            <div className="blotter-header">
              <span className="section-header" style={{margin:0,border:'none',paddingBottom:0}}>Trade Blotter</span>
              <span style={{fontSize:'var(--font-size-xs)',color:'var(--text-muted)'}}>
                {bsdexTrades.length === 0
                  ? 'No trades yet — spread must exceed B/E and z-score must reach threshold'
                  : `${bsdexTrades.length} trade${bsdexTrades.length !== 1 ? 's' : ''} · fees paid: €${bsdexStatus?.total_fees_eur?.toFixed(4) ?? '0.0000'}`}
              </span>
            </div>
            {bsdexTrades.length > 0 && (
              <table className="dense-table">
                <thead>
                  <tr>
                    <th>Time</th><th>Market</th><th>Route</th>
                    <th className="right">Amount</th><th className="right">Gross (€)</th>
                    <th className="right">Fees (€)</th><th className="right">Net (€)</th><th>Tier</th>
                  </tr>
                </thead>
                <tbody>
                  {bsdexTrades.map((t, i) => {
                    const gross = (t.pnl_eur ?? 0) + (t.fees_eur ?? 0);
                    return (
                      <tr key={i}>
                        <td style={{color:'var(--text-muted)'}}>{t.timestamp?.slice(11,19) ?? '—'}</td>
                        <td className="text">{t.market?.toUpperCase()}</td>
                        <td className="text" style={{color:'var(--text-secondary)'}}>{t.buy_exchange} → {t.sell_exchange}</td>
                        <td className="right">{t.amount?.toFixed(5) ?? '—'}</td>
                        <td className={`right ${gross >= 0 ? 'pnl-pos' : 'pnl-neg'}`}>{gross.toFixed(4)}</td>
                        <td className="right pnl-neg">{t.fees_eur?.toFixed(4) ?? '—'}</td>
                        <td className={`right ${(t.pnl_eur ?? 0) >= 0 ? 'pnl-pos' : 'pnl-neg'}`}><strong>{t.pnl_eur?.toFixed(4) ?? '—'}</strong></td>
                        <td style={{color:'var(--text-muted)',fontFamily:'var(--font-sans)'}}>{t.tier ?? '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>

      {/* ══ STATUS BAR ═══════════════════════════════════════════ */}
      <div className="status-bar">
        <span>Venue A: Bitstamp EUR (BSDEX proxy)</span>
        <span className="status-sep">|</span>
        <span>Venue B: Binance USDT→EUR (LMAX fee model)</span>
        <span className="status-sep">|</span>
        <span>FX: ECB/Frankfurter (60s)</span>
        <span className="status-sep">|</span>
        <span>All trades simulated</span>
        <span className="status-sep">|</span>
        <span>STAT ARB v1.0</span>
      </div>

      </div>{/* end .dashboard */}
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
