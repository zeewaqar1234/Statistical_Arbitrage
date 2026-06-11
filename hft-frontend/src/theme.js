import { createTheme } from '@mui/material/styles';

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary:    { main: '#FF8C00' },
    secondary:  { main: '#FFB020' },
    background: { default: '#0A0E17', paper: '#111620' },
    text:       { primary: '#E8EAED', secondary: '#6B7B8D' },
    success:    { main: '#00B060' },
    error:      { main: '#FF3B3B' },
    warning:    { main: '#FFD60A' },
    divider:    '#1E2736',
  },
  typography: {
    fontFamily: "'IBM Plex Sans', -apple-system, sans-serif",
    fontSize: 13,
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: { body: { background: '#0A0E17' } },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 0,
          border: '1px solid #1E2736',
          boxShadow: 'none',
          background: '#111620',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: 'uppercase',
          fontWeight: 600,
          borderRadius: 0,
          letterSpacing: '0.5px',
          fontSize: 11,
        },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: { background: '#161C28', border: '1px solid #1E2736', borderRadius: 0 },
      },
    },
  },
});

export default theme;
