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
  ReferenceArea,
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
  const [hbtDataSource, setHbtDataSource] = useState('candles');
  const [hbtQuotePath, setHbtQuotePath] = useState('data/quotes');
  const [hbtLatency, setHbtLatency] = useState(300);
  const [hbtSpreadModel, setHbtSpreadModel] = useState('conservative');
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

  // Trade timestamp set for dot markers on the live chart
  const bsdexTradeTimeSet = useMemo(
    () => new Set(bsdexTrades.map(t => t.timestamp?.slice(11, 16))),
    [bsdexTrades]
  );

  // Break-even derived from local fee state (always up to date)
  const bsdexBreakevenPct = (bsdexFeeA + bsdexFeeB) * 100 + (bsdexStatus?.fx_cost_bps ?? 1) / 100;


  const bsdexZScore          = bsdexMarketData?.z_score ?? null;
  const bsdexThreshold       = bsdexMarketData?.threshold ?? null;
  const bsdexSpread          = bsdexMarketData?.spread_eur ?? null;
  const bsdexSpreadPct       = bsdexMarketData?.spread_pct ?? null;
  const bsdexSignalState     = bsdexMarketData?.signal_state ?? 'HOLD';
  const bsdexSignalTriggered = bsdexSignalState === 'SIGNAL';
  const bsdexSignalGated     = ['SIGNAL_GATED', 'FX_STALE', 'BOOK_STALE', 'FILL_FAILED'].includes(bsdexSignalState);
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
        data_source: hbtDataSource,
        quote_path: hbtQuotePath,
        latency_ms: hbtLatency,
        spread_model: hbtSpreadModel,
        start_dt:      new Date(`${hbtStartDt}Z`).toISOString(),
        end_dt:        new Date(`${hbtEndDt}Z`).toISOString(),
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
      hbtFeeMode, hbtTierIdx, bsdexVolumeTiers, hbtDataSource, hbtQuotePath, hbtLatency, hbtSpreadModel]);

  // Excel export via SheetJS — handles dual-scenario result shape
  const handleExportExcel = useCallback(() => {
    if (!hbtResult) return;
    import('xlsx').then((XLSX) => {
      const wb = XLSX.utils.book_new();

      const writeScenario = (scenario, label) => {
        if (!scenario) return;
        const sumRows = Object.entries(scenario.summary).map(([k, v]) => ({ Field: k, Value: typeof v === 'object' ? JSON.stringify(v) : v }));
        XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(sumRows), `${label} Summary`);

        if (scenario.trades?.length > 0) {
          const tradeRows = scenario.trades.map((t) => ({
            Timestamp:      t.ts_str?.slice(0, 19).replace('T', ' '),
            Direction:      t.direction,
            'Signal %': t.signal_spread_pct,
            'Realized %': t.realized_spread_pct,
            'FX cost EUR': t.fx_cost_eur,
            'Signal timestamp': t.signal_ts,
            'Fill timestamp': t.fill_ts,
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
    : bsdexSignalGated    ? bsdexSignalState
    : bsdexSignalCooldown ? 'COOLDOWN'
    : bsdexSignalState;

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <div className={`dashboard${activeTab === 'backtest' ? ' tab-backtest' : activeTab === 'bsdex' ? ' tab-bsdex-live' : ''}`}>

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

      {/* ══ LEFT PANEL — hidden in bsdex-live mode ═══════════════ */}
      <aside className="left-panel" />

      {/* ══ CENTER PANEL ═════════════════════════════════════════ */}
      <div className="center-panel">

        {/* ══ BSDEX vs WORLD — redesigned live tab ══════════════════ */}
        {activeTab === 'bsdex' && (() => {
          const priceModel    = bsdexMarketData?.price_model ?? null;
          const isVwap        = priceModel && priceModel.toLowerCase().includes('vwap');
          const fxAgeSec      = bsdexStatus?.fx_age_sec ?? null;
          const fxAgeStale    = fxAgeSec == null || fxAgeSec > 5;
          const cumPnl        = bsdexStatus?.total_pnl_eur ?? 0;
          const cumPnlPos     = cumPnl >= 0;
          const totalTrades   = bsdexStatus?.total_trades ?? 0;
          const winRate       = bsdexStatus?.win_rate_pct ?? 0;
          const totalFees     = bsdexStatus?.total_fees_eur ?? 0;
          // Depth / slippage / WS status from live engine
          const bsWsDepth    = bsdexMarketData?.bs_ws_depth ?? false;
          const depthAEur    = bsdexMarketData?.depth_a_eur ?? null;
          const depthBEur    = bsdexMarketData?.depth_b_eur ?? null;
          const slipABps     = bsdexMarketData?.vwap_slip_a_bps ?? null;
          const slipBBps     = bsdexMarketData?.vwap_slip_b_bps ?? null;
          const depthWarn    = bsdexMarketData?.depth_warn ?? false;
          const capitalEur   = bsdexMarketData?.capital_eur ?? 0;

          // tradeTsSet is computed at component level (see bsdexTradeTimeSet below)

          return (
            <div className="live-layout">

              {/* ── ROW 1: Hero strip ──────────────────────────────── */}
              <div className="live-hero-strip">
                {/* Cell 1: Spread */}
                <div className="live-hero-cell">
                  <div className="live-hero-label">Spread</div>
                  <div className={`live-hero-value ${bsdexSpread != null ? (bsdexSpread >= 0 ? 'pnl-pos' : 'pnl-neg') : ''}`}>
                    {bsdexSpread != null ? `${bsdexSpread >= 0 ? '+' : ''}€${bsdexSpread.toFixed(2)}` : '—'}
                  </div>
                  <div className={`live-hero-sub ${bsdexSpreadPct != null ? (bsdexSpreadPct >= 0 ? 'pnl-pos' : 'pnl-neg') : ''}`}>
                    {bsdexSpreadPct != null ? `${bsdexSpreadPct >= 0 ? '+' : ''}${bsdexSpreadPct.toFixed(4)}%` : '—'}
                    <span style={{color:'var(--text-muted)',marginLeft:8}}>B/E {bsdexBreakevenPct.toFixed(3)}%</span>
                  </div>
                </div>
                {/* Cell 2: Z-Score vs Threshold */}
                <div className="live-hero-cell">
                  <div className="live-hero-label">Z-Score / Threshold</div>
                  <div className={`live-hero-value ${bsdexSignalTriggered ? 'pnl-pos' : ''}`}>
                    {bsdexZScore != null ? bsdexZScore.toFixed(3) : '—'}
                  </div>
                  <div className="live-hero-sub">
                    threshold <span style={{color:'var(--accent-red)'}}>{bsdexThreshold?.toFixed(3) ?? '—'}</span>
                  </div>
                </div>
                {/* Cell 3: Signal state */}
                <div className="live-hero-cell" style={{justifyContent:'center'}}>
                  <div className="live-hero-label">Signal State</div>
                  <div style={{marginTop:6}}>
                    <span className={`tag ${signalTagClass}`} style={{fontSize:18,padding:'4px 14px',letterSpacing:2}}>
                      {signalTagText}
                    </span>
                  </div>
                  {bsdexSignalTriggered && (
                    <div className="live-hero-sub" style={{marginTop:6}}>
                      <span className="exec-leg buy" style={{marginRight:10}}>BUY {bsdexMarketData?.b_ask?.toFixed(2)}</span>
                      <span className="exec-leg sell">SELL {bsdexMarketData?.a_bid?.toFixed(2)}</span>
                    </div>
                  )}
                  {bsdexSignalGated && (
                    <div className="live-hero-sub" style={{color:'var(--accent-yellow)',marginTop:4}}>
                      spread &lt; B/E
                    </div>
                  )}
                  {bsdexSignalCooldown && (
                    <div className="live-hero-sub" style={{color:'var(--text-muted)',marginTop:4}}>
                      cooldown active
                    </div>
                  )}
                </div>
                {/* Cell 4: Cumulative PnL */}
                <div className="live-hero-cell">
                  <div className="live-hero-label">Cumulative PnL</div>
                  <div className={`live-hero-value ${cumPnlPos ? 'pnl-pos' : 'pnl-neg'}`}>
                    {cumPnlPos ? '+' : ''}€{cumPnl.toFixed(4)}
                  </div>
                  <div className="live-hero-sub">
                    {totalTrades} trade{totalTrades !== 1 ? 's' : ''}
                    <span style={{marginLeft:8}}>WR {winRate.toFixed(1)}%</span>
                  </div>
                </div>
              </div>

              {/* ── ROW 2: Hero chart ───────────────────────────────── */}
              <div className="live-chart-section">
                <div className="live-chart-header">
                  <span className="live-chart-title">Cross-Exchange Spread — {bsdexBase}-EUR</span>
                  <div className="live-chart-badges">
                    {/* price_model badge */}
                    {priceModel && (
                      <span className={`live-badge ${isVwap ? 'live-badge-green' : 'live-badge-yellow'}`}>
                        {isVwap ? 'VWAP depth' : 'top-of-book fallback'}
                      </span>
                    )}
                    {/* Bitstamp data source badge */}
                    <span className={`live-badge ${bsWsDepth ? 'live-badge-green' : 'live-badge-yellow'}`}
                          title={bsWsDepth ? 'Bitstamp order book via WebSocket (sub-second)' : 'Waiting for fresh Bitstamp WS depth'}>
                      BS {bsWsDepth ? 'WS ✓' : 'WS waiting'}
                    </span>
                    {/* Depth warning */}
                    {depthWarn && (
                      <span className="live-badge live-badge-red"
                            title={`Available book depth < 1.5× capital (€${capitalEur?.toFixed(0)}). VWAP slippage will be high.`}>
                        ⚠ thin book
                      </span>
                    )}
                    {/* FX age badge */}
                    {fxAgeSec != null && (
                      <span className={`live-badge ${fxAgeStale ? 'live-badge-yellow' : 'live-badge-muted'}`}>
                        FX {Math.round(fxAgeSec)}s{fxAgeStale ? ' ⚠' : ''}
                      </span>
                    )}
                    <select className="pair-select" value={bsdexMarket} onChange={(e) => setBsdexMarket(e.target.value)}>
                      <option value="btc-eur">BTC/EUR</option>
                      <option value="eth-eur">ETH/EUR</option>
                    </select>
                  </div>
                </div>
                <div className="live-chart-body">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={bsdexChartData} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
                      <CartesianGrid stroke="#1E2736" strokeDasharray="3 3" />
                      <XAxis dataKey="time" tick={{ fill: '#6B7B8D', fontSize: 10, fontFamily: 'IBM Plex Mono' }}
                        axisLine={{ stroke: '#1E2736' }} tickLine={{ stroke: '#1E2736' }} />
                      <YAxis tick={{ fill: '#6B7B8D', fontSize: 10, fontFamily: 'IBM Plex Mono' }}
                        axisLine={{ stroke: '#1E2736' }} tickLine={{ stroke: '#1E2736' }}
                        tickFormatter={(v) => `${v.toFixed(3)}%`} />
                      <Tooltip content={<BsdexSpreadTooltip />} />
                      {/* Break-even shaded band */}
                      <ReferenceArea y1={-bsdexBreakevenPct} y2={bsdexBreakevenPct}
                        fill="rgba(255,140,0,0.06)" stroke="none" />
                      <ReferenceLine y={0} stroke="#3D4F63" strokeWidth={0.5} />
                      <ReferenceLine y={bsdexBreakevenPct} stroke="#FF8C00" strokeDasharray="4 4"
                        label={{ value: 'B/E', fill: '#FF8C00', fontSize: 9, position: 'insideTopRight' }} />
                      <ReferenceLine y={-bsdexBreakevenPct} stroke="#FF8C00" strokeDasharray="4 4" />
                      <Area type="monotone" dataKey="spreadPct" name="Spread %" dot={(props) => {
                        const { cx, cy, payload } = props;
                        if (!bsdexTradeTimeSet.has(payload.time)) return null;
                        return <circle key={cx} cx={cx} cy={cy} r={4} fill="#FF3B3B" stroke="#FF3B3B" />;
                      }} strokeWidth={1.5}
                        stroke="#4FC3F7" fill="rgba(79,195,247,0.08)" isAnimationActive={false} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* ── ROW 3: Blotter (60%) + Session stats (40%) ─────── */}
              <div className="live-bottom-row">
                {/* Left: trade blotter */}
                <div className="live-blotter-col">
                  <div className="live-col-header">
                    <span className="live-col-header-title">Trade Blotter</span>
                    <span style={{fontSize:'var(--font-size-xs)',color:'var(--text-muted)'}}>
                      {bsdexTrades.length === 0
                        ? 'no trades yet'
                        : `${bsdexTrades.length} trade${bsdexTrades.length !== 1 ? 's' : ''} · fees €${totalFees.toFixed(4)}`}
                    </span>
                  </div>
                  <div className="live-blotter-scroll">
                    {bsdexTrades.length > 0 ? (
                      <table className="dense-table">
                        <thead>
                          <tr>
                            {['Time', 'Market', 'Buy venue', 'Buy price', 'Sell venue', 'Sell price', 'Quantity', 'Notional EUR', 'Signal %', 'Realized %', 'Gross', 'Fees', 'Net', 'Model'].map(label => <th key={label}>{label}</th>)}
                          </tr>
                        </thead>
                        <tbody>
                          {bsdexTrades.map((t, i) => (
                            <tr key={i}>
                              <td>{t.timestamp?.slice(11,19) ?? '—'}</td>
                              <td>{t.market?.toUpperCase() ?? '—'}</td>
                              <td>{t.buy_exchange}</td>
                              <td className="right mono">{t.buy_price_eur?.toFixed(2)}</td>
                              <td>{t.sell_exchange}</td>
                              <td className="right mono">{t.sell_price_eur?.toFixed(2)}</td>
                              <td className="right mono">{t.amount?.toFixed(6)} {t.market?.split('-')[0]?.toUpperCase()}</td>
                              <td className="right mono">{t.notional_eur?.toFixed(2) ?? '—'}</td>
                              <td className="right mono">{t.signal_spread_pct?.toFixed(4) ?? '—'}</td>
                              <td className="right mono">{t.realized_spread_pct?.toFixed(4) ?? '—'}</td>
                              <td className="right mono">{t.gross_eur?.toFixed(4) ?? '—'}</td>
                              <td className="right mono pnl-neg">{t.fees_eur?.toFixed(4) ?? '—'}</td>
                              <td className={`right mono ${(t.pnl_eur ?? 0) >= 0 ? 'pnl-pos' : 'pnl-neg'}`}>{t.pnl_eur?.toFixed(4)}</td>
                              <td title={`Observed fill latency: ${t.fill_latency_ms?.toFixed(0)} ms`}>{t.price_model}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : (
                      <div style={{padding:'16px 10px',color:'var(--text-muted)',fontSize:'var(--font-size-xs)'}}>
                        Spread must exceed B/E ({bsdexBreakevenPct.toFixed(3)}%) and z-score must reach threshold.
                      </div>
                    )}
                  </div>
                </div>

                {/* Right: session stats */}
                <div className="live-stats-col">
                  <div className="live-col-header" style={{padding:'5px 0 5px 0',border:'none',marginBottom:4}}>
                    <span className="live-col-header-title">Session Stats</span>
                  </div>
                  <div className="live-stats-grid">
                    {[
                      ['Trades',    totalTrades,                  ''],
                      ['Win Rate',  `${winRate.toFixed(1)}%`,     winRate >= 50 ? 'pnl-pos' : ''],
                      ['Cum PnL',   `${cumPnlPos?'+':''}€${cumPnl.toFixed(4)}`, cumPnlPos ? 'pnl-pos' : 'pnl-neg'],
                      ['Fees Paid', `€${totalFees.toFixed(4)}`,  'pnl-neg'],
                      ['FX cost', `${bsdexStatus?.fx_cost_bps ?? 1} bps / USDT leg`, ''],
                      ['Fill latency', `${bsdexStatus?.fill_latency_ms ?? 300} ms minimum`, ''],
                      ['Failed fills', bsdexStatus?.execution_failures?.length ?? 0, ''],
                      ['ECB fixing (reference)', bsdexStatus?.ecb_fixing?.toFixed(5) ?? '—', ''],
                      ['FX Rate',   bsdexStatus?.fx_rate_usd_eur?.toFixed(5) ?? '—', ''],
                      ['FX Age',    fxAgeSec != null ? `${Math.round(fxAgeSec)}s` : '—', fxAgeStale ? 'pnl-neg' : ''],
                      ['Signal',    signalTagText, signalTagClass === 'tag-green' ? 'pnl-pos' : ''],
                      // Data source quality
                      ['BS Feed',   bsWsDepth ? 'WebSocket ✓' : 'REST (init)', bsWsDepth ? 'pnl-pos' : 'pnl-neg'],
                      // Real-time book depth — key credibility metric
                      ['Depth A',   depthAEur != null ? `€${(depthAEur/1000).toFixed(1)}k` : '—',
                                    (depthAEur != null && capitalEur > 0 && depthAEur < capitalEur * 1.5) ? 'pnl-neg' : 'pnl-pos'],
                      ['Depth B',   depthBEur != null ? `€${(depthBEur/1000).toFixed(1)}k` : '—', 'pnl-pos'],
                      // VWAP slippage vs top-of-book — shows model realism
                      ['Slip A',    slipABps != null ? `${slipABps.toFixed(2)} bps` : '—', slipABps != null && slipABps > 5 ? 'pnl-neg' : ''],
                      ['Slip B',    slipBBps != null ? `${slipBBps.toFixed(2)} bps` : '—', slipBBps != null && slipBBps > 5 ? 'pnl-neg' : ''],
                    ].map(([label, val, cls]) => (
                      <div className="live-stats-cell" key={label}>
                        <div className="live-stats-label">{label}</div>
                        <div className={`live-stats-value ${cls}`}>{val ?? '—'}</div>
                      </div>
                    ))}
                  </div>
                  {/* Venue prices compact */}
                  <div style={{background:'var(--bg-panel)',border:'1px solid var(--border)',padding:'6px 10px',marginTop:6}}>
                    <div style={{fontSize:'var(--font-size-xs)',color:'var(--accent-orange)',fontWeight:700,letterSpacing:'0.8px',textTransform:'uppercase',marginBottom:4}}>Live Quotes</div>
                    <div style={{display:'grid',gridTemplateColumns:'auto 1fr 1fr',gap:'2px 10px',fontSize:'var(--font-size-xs)'}}>
                      <span style={{color:'var(--text-muted)'}}>A bid</span>
                      <span className={`mono ${bsdexPriceTrend.venueA === 'positive' ? 'pnl-pos' : bsdexPriceTrend.venueA === 'negative' ? 'pnl-neg' : ''}`}>
                        {bsdexMarketData?.a_bid != null ? `€${bsdexMarketData.a_bid.toFixed(2)}` : '—'}
                      </span>
                      <span className="mono" style={{color:'var(--text-secondary)'}}>
                        ask {bsdexMarketData?.a_ask != null ? `€${bsdexMarketData.a_ask.toFixed(2)}` : '—'}
                      </span>
                      <span style={{color:'var(--text-muted)'}}>B bid</span>
                      <span className={`mono ${bsdexPriceTrend.venueB === 'positive' ? 'pnl-pos' : bsdexPriceTrend.venueB === 'negative' ? 'pnl-neg' : ''}`}>
                        {bsdexMarketData?.b_bid != null ? `€${bsdexMarketData.b_bid.toFixed(2)}` : '—'}
                      </span>
                      <span className="mono" style={{color:'var(--text-secondary)'}}>
                        ask {bsdexMarketData?.b_ask != null ? `€${bsdexMarketData.b_ask.toFixed(2)}` : '—'}
                      </span>
                    </div>
                    {priceModel && (
                      <div style={{marginTop:4,fontSize:'var(--font-size-xs)',color: isVwap ? 'var(--accent-green)' : 'var(--accent-yellow)'}}>
                        model: {priceModel}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* ── ROW 4: Collapsible Fee & Capital Configuration ──── */}
              <details className="live-config-details">
                <summary className="live-config-summary">
                  <span className="summary-label">Fee &amp; Capital</span>
                  <span>
                    Tier: {bsdexFeeMode === 'auto' && bsdexVolumeTiers[bsdexTierIdx]
                      ? bsdexVolumeTiers[bsdexTierIdx].label
                      : 'manual'}
                  </span>
                  <span>· A {(bsdexFeeA*100).toFixed(2)}%</span>
                  <span>· B {(bsdexFeeB*100).toFixed(2)}%</span>
                  <span>· B/E {bsdexBreakevenPct.toFixed(3)}%</span>
                  <span>· Cap €{bsdexCapitalEur.toLocaleString()}</span>
                  <span className="summary-edit">[edit]</span>
                </summary>
                <div className="live-config-body">
                  <div className="rp-section" style={{border:'none',padding:0}}>
                    <div className="fee-grid">
                      <div className="fee-mode-toggle" style={{width:180}}>
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
                      <div style={{display:'flex',gap:10}}>
                        <div className="fee-field" style={{flex:1}}>
                          <label>Venue A Taker</label>
                          <div className="fee-input-row">
                            <input type="number" className="bb-input" min="0" max="5" step="0.001"
                              value={(bsdexFeeA*100).toFixed(3)} readOnly={bsdexFeeMode === 'auto'}
                              onChange={(e) => setBsdexFeeA(Math.max(0, parseFloat(e.target.value)||0)/100)} />
                            <span className="fee-unit-label">%</span>
                          </div>
                        </div>
                        <div className="fee-field" style={{flex:1}}>
                          <label>Venue B Taker</label>
                          <div className="fee-input-row">
                            <input type="number" className="bb-input" min="0" max="5" step="0.001"
                              value={(bsdexFeeB*100).toFixed(3)} readOnly={bsdexFeeMode === 'auto'}
                              onChange={(e) => setBsdexFeeB(Math.max(0, parseFloat(e.target.value)||0)/100)} />
                            <span className="fee-unit-label">%</span>
                          </div>
                        </div>
                        <div className="fee-field" style={{flex:1}}>
                          <label>Capital (EUR)</label>
                          <input type="number" className="bb-input" min="100" step="1000" value={bsdexCapitalEur}
                            onChange={(e) => setBsdexCapitalEur(parseFloat(e.target.value) || 1000)} />
                        </div>
                      </div>
                      <div className="be-box" style={{width:'fit-content'}}>
                        <span className="be-label">B/E Spread</span>
                        <span className="be-value" style={{marginLeft:12}}>{bsdexBreakevenPct.toFixed(3)}%</span>
                      </div>
                      <div className="config-apply-row">
                        <button type="button" className="bb-btn" onClick={handleBsdexApplyConfig} disabled={bsdexConfigSaving}>
                          {bsdexConfigSaving ? '…' : 'Apply'}
                        </button>
                        {bsdexConfigApplied && <span className="config-ok">✓ Applied</span>}
                      </div>
                    </div>
                  </div>
                </div>
              </details>

            </div>
          );
        })()}

        {/* --- BACKTEST center --- */}
        {activeTab === 'backtest' && (
          <div className="backtest-layout">
            <div className="bt-config-panel">
              <div className="section-header">BSDEX vs World — Historical Backtest</div>
              <p style={{fontSize:'var(--font-size-xs)',color:'var(--text-secondary)',margin:'0 0 10px',lineHeight:1.6}}>
                Uses <strong>recorded executable quotes</strong> or 1-minute candles from Bitstamp and Binance (EURUSDT FX). Candles are an approximation and may contain stale closes.
                Runs the same spread / z-score logic as the live strategy (60-min rolling window, threshold 1.5σ, 30-min trade cooldown).
                All prices and PnL in <strong>EUR</strong>. Candle range: up to 7 days; recorded quotes can span longer.
              </p>
              {hbtDataSource === 'quotes' && <p style={{fontSize:'var(--font-size-xs)', color:'var(--text-secondary)'}}>
                Quotes are recorded automatically while the backend is running and connected. Allow at least 60 minutes, then choose dates within the recorded period. Earlier order books are unavailable; use Candles for past dates.
                {bsdexStatus?.quote_recording && <span> Recorder: {bsdexStatus.quote_recording.state.replaceAll('_', ' ')}.
                  {bsdexStatus.quote_recording.last_snapshot && <> Latest snapshot: {new Date(bsdexStatus.quote_recording.last_snapshot).toISOString()}.</>}
                </span>}
              </p>}
              <div className="bt-config-grid">
                <div className="bt-field">
                  <label>Data source</label>
                  <select className="bb-select" value={hbtDataSource} onChange={e => setHbtDataSource(e.target.value)}>
                    <option value="candles">Candles</option><option value="quotes">Recorded quotes</option>
                  </select>
                </div>
                {hbtDataSource === 'candles' && <div className="bt-field">
                  <label>Spread model</label>
                  <select className="bb-select" value={hbtSpreadModel} onChange={e => setHbtSpreadModel(e.target.value)}>
                    <option value="conservative">Conservative (A: 5 bps)</option>
                    <option value="calibrated">Calibrated from earlier recorded quotes</option>
                  </select>
                </div>}
                {(hbtDataSource === 'quotes' || hbtSpreadModel === 'calibrated') && <div className="bt-field">
                  <label>Quote file or directory (on server)</label>
                  <input className="bb-input" value={hbtQuotePath} onChange={e => setHbtQuotePath(e.target.value)} />
                </div>}
                {hbtDataSource === 'quotes' && <div className="bt-field">
                  <label>Fill latency (ms)</label>
                  <input className="bb-input" type="number" min="0" value={hbtLatency} onChange={e => setHbtLatency(Number(e.target.value))} />
                </div>}

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
                <span className="be-value" style={{marginLeft:12}}>{((hbtFeeA+hbtFeeB)*100 + (hbtSymbol === 'btc-eur-kraken' ? 0 : 0.01)).toFixed(3)}%</span>
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
                <div style={{fontSize:'var(--font-size-sm)',color:'var(--text-secondary)'}}>Running backtest on the selected data source…</div>
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
              const fxTag  = meta.data_source === 'recorded_quotes' ? 'EUR/USDT recorded WS' : meta.fx_granularity === '1m' ? '1m intraday' : meta.fx_granularity === 'none-eur-native' ? 'native EUR' : 'daily fallback ⚠';
              const ec     = rs.exec_costs ?? {};
              const fillLabel = meta.data_source === 'recorded_quotes' ? `First snapshot ≥ ${meta.fill_latency_ms} ms (1s recording)` : 'Bar i+1 (1-min lag)';

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
                    <span>Model: {ec.spread_model}</span>
                    <span>FX cost: {ec.fx_cost_bps} bps on USDT leg</span>
                    <span>Failed fills: {rs.failed_fills ?? 0}</span>
                    <span style={{marginLeft:'auto',color:'var(--text-muted)'}}>Fills: {fillLabel}</span>
                  </div>

                  {/* ── REALISTIC headline KPI row ───────────────────── */}
                  <div style={{marginBottom:4,fontSize:'var(--font-size-xs)',color:'#4FC3F7',fontWeight:600,letterSpacing:'0.06em'}}>REALISTIC (bid-ask + slippage costs applied)</div>
                  <div className="bt-kpi-row" style={{marginBottom:10}}>
                    {[
                      ['Gross PnL',    `€${rs.gross_pnl_eur?.toFixed(4)}`,   rs.gross_pnl_eur >= 0 ? 'pnl-pos' : 'pnl-neg'],
                      ['Total Fees',   `−€${rs.total_fees_eur?.toFixed(4)}`,  'pnl-neg'],
                      ['Net PnL',      `€${rs.total_pnl_eur?.toFixed(4)}`,    netPos ? 'pnl-pos' : 'pnl-neg'],
                      ['Carry', `€${rs.carry_eur?.toFixed(4)}`, 'pnl-neg'],
                      ['Net after carry', `€${rs.net_after_carry_eur?.toFixed(4)}`, rs.net_after_carry_eur >= 0 ? 'pnl-pos' : 'pnl-neg'],
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
                        <tr><td>Scenario shown</td><td>{us ? 'Realistic + upper bound' : 'Recorded executable depth'}</td><td>Never present upper bound alone</td></tr>
                        <tr><td>Signal threshold</td><td>{rs.zscore_threshold}σ rolling z-score</td><td>60-min window</td></tr>
                        <tr><td>Execution</td><td>{fillLabel}</td><td>Gate on signal; book fill regardless of sign</td></tr>
                        <tr><td>Carry</td><td>4 pools × capital × 2.50% × hours / 8760</td><td>{ec.carry_dfr_source}</td></tr>
                        <tr><td>FX cost</td><td>{ec.fx_cost_bps} bps</td><td>Charged once on the USDT leg</td></tr>
                        <tr><td>Spread model</td><td>{ec.spread_model}</td><td>{ec.calibration_source ?? 'Recorded book or conservative assumption'}</td></tr>
                        <tr><td>Exec costs (realistic)</td><td>HS A={ec.half_spread_bps_venue_a} bps · HS B={ec.half_spread_bps_venue_b} bps · Slip {ec.slippage_bps} bps</td><td>Mid→executable price adjustment</td></tr>
                        <tr><td>Break-even gate</td><td>{rs.breakeven_spread_pct?.toFixed(3)}%</td><td>Applied to adjusted prices</td></tr>
                        <tr><td>Cooldown</td><td>{rs.trade_cooldown_min} min</td><td>Toxic flow guard</td></tr>
                        <tr><td>FX</td><td>{fxTag}</td><td>Binance EURUSDT 1m primary; daily ECB fallback</td></tr>
                        <tr><td>Tier</td><td>{rs.tier_label}</td><td>{'P7: >$20M default; >$1B aspirational'}</td></tr>
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
                              <th>Time (UTC)</th><th>Direction</th><th>Signal %</th><th>Realized %</th><th>Z-Score</th>
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
                                <td>{t.signal_spread_pct?.toFixed(4)}%</td><td>{t.realized_spread_pct?.toFixed(4)}%</td>
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
                      Review the recorded data coverage and selected cost assumptions.
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        )}
      </div>

      {/* ══ RIGHT PANEL — hidden in bsdex-live mode ══════════════ */}
      <aside className="right-panel" />

      {/* ══ BLOTTER — hidden in bsdex-live mode (blotter is now inside live-layout) */}
      <div className="blotter" />

      {/* ══ STATUS BAR ═══════════════════════════════════════════ */}
      <div className="status-bar">
        <span>Venue A: Bitstamp EUR (BSDEX proxy)</span>
        <span className="status-sep">|</span>
        <span>Venue B: Binance USDT→EUR (LMAX fee model)</span>
        <span className="status-sep">|</span>
        <span>FX: Binance EUR/USDT live (WS)</span>
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
