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
} from 'recharts';

const API_BASE_URL = config.apiUrl;
const SYMBOLS = ['BTC/USDT', 'ETH/USDT'];
const REFRESH_INTERVAL = 2000;
const MAX_HISTORY_POINTS = 300;
const MAX_ACTIVITY_ROWS = 20;
const CHART_ANIMATION = { isAnimationActive: true, animationDuration: 400 };

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

function AppContent() {
  const [selectedSymbol, setSelectedSymbol] = useState(SYMBOLS[0]);
  const [isRunning, setIsRunning] = useState(true);
  const [currentTime, setCurrentTime] = useState(new Date());
  const [history, setHistory] = useState([]);
  const [priceTrend, setPriceTrend] = useState({ binance: '', kraken: '' });
  const prevPricesRef = useRef({ binance: null, kraken: null });

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

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!marketData) return;
    const threshold = marketData.adaptive_threshold ?? 1;
    const b = marketData.binance_price ?? marketData.mid_price ?? null;
    const k = marketData.kraken_price ?? null;

    setHistory((prev) => [
      ...prev,
      {
        time: formatChartTime(marketData.timestamp),
        binance: b ?? 0,
        kraken: k ?? 0,
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
          <div className="connection-status">
            <span className={`status-dot ${isConnected ? 'connected' : 'disconnected'}`} />
            {isConnected ? 'Connected' : isRunning ? 'Connecting…' : 'Stopped'}
          </div>
          <span className="current-time">{formatTime(currentTime)}</span>
        </div>
      </header>

      <main className="dashboard">
        {marketDataError && (
          <div className="error-banner">
            Unable to load market data. Check that the backend is running at {API_BASE_URL}.
          </div>
        )}

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

        <section className="charts-stack">
          <div className="card chart-card chart-card-tall">
            <div className="card-title">Price Comparison</div>
            {!hasChartData ? (
              <div className="skeleton skeleton-chart-tall" />
            ) : (
              <div className="chart-container chart-container-tall">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={history} margin={{ top: 12, right: 24, left: 8, bottom: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F0F0F0" />
                    <XAxis dataKey="time" stroke="#6C757D" fontSize={11} tick={{ fill: '#6C757D' }} />
                    <YAxis stroke="#6C757D" fontSize={11} domain={['auto', 'auto']} tick={{ fill: '#6C757D' }} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend />
                    <Line type="monotone" dataKey="binance" name="Binance" stroke="#0D6EFD" dot={false} strokeWidth={2} {...CHART_ANIMATION} />
                    <Line type="monotone" dataKey="kraken" name="Kraken" stroke="#FD7E14" dot={false} strokeWidth={2} {...CHART_ANIMATION} />
                  </LineChart>
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
