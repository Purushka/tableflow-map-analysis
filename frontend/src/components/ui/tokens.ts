/** Design tokens for the TableFlow dark theme */

export const colors = {
  // Background layers (dark to light)
  bg: {
    base: '#0f172a',      // deepest background
    surface: '#1e293b',   // cards, panels
    elevated: '#334155',  // hover, active states
  },
  // Borders
  border: {
    subtle: '#334155',
    strong: '#475569',
  },
  // Text
  text: {
    primary: '#e2e8f0',
    secondary: '#94a3b8',
    muted: '#64748b',
    disabled: '#475569',
  },
  // Accent colors
  accent: {
    blue: '#3b82f6',
    emerald: '#10b981',
    amber: '#f59e0b',
    red: '#ef4444',
    violet: '#8b5cf6',
    cyan: '#06b6d4',
    pink: '#ec4899',
  },
  // Status
  status: {
    success: '#10b981',
    warning: '#f59e0b',
    error: '#ef4444',
    info: '#3b82f6',
  },
} as const;

export const spacing = {
  xs: '0.25rem',   // 4px
  sm: '0.5rem',    // 8px
  md: '0.75rem',   // 12px
  lg: '1rem',      // 16px
  xl: '1.5rem',    // 24px
} as const;

export const fontSize = {
  xs: '0.625rem',  // 10px
  sm: '0.6875rem', // 11px
  md: '0.75rem',   // 12px
  base: '0.875rem',// 14px
} as const;

export const radius = {
  sm: '0.25rem',   // 4px
  md: '0.375rem',  // 6px
  lg: '0.5rem',    // 8px
  full: '9999px',
} as const;
