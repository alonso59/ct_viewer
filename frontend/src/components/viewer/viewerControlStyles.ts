export function viewerControlButtonSx(active = false) {
  return {
    minHeight: 34,
    minWidth: 34,
    px: 1,
    py: 0.25,
    border: '1px solid',
    borderColor: active ? 'primary.main' : 'rgba(255,255,255,0.2)',
    borderRadius: 1,
    backgroundColor: active ? 'rgba(96,165,250,0.18)' : 'rgba(0,0,0,0.66)',
    backdropFilter: 'blur(8px)',
    color: active ? 'primary.main' : 'rgba(226,232,240,0.86)',
    lineHeight: 1.1,
    fontSize: '0.72rem',
    fontWeight: 700,
    textTransform: 'none',
    boxShadow: active ? '0 0 0 1px rgba(96,165,250,0.16) inset' : 'none',
    transition: 'border-color 0.12s ease, background-color 0.12s ease, color 0.12s ease',
    '& .MuiButton-startIcon': {
      mr: 0.55,
      ml: -0.15,
    },
    '& .MuiSvgIcon-root': {
      fontSize: '1rem',
    },
    '&:hover': {
      borderColor: active ? 'primary.light' : 'rgba(255,255,255,0.48)',
      backgroundColor: active ? 'rgba(96,165,250,0.24)' : 'rgba(0,0,0,0.82)',
      color: active ? 'primary.light' : '#fff',
    },
    '&:focus-visible': {
      outline: '2px solid rgba(147,197,253,0.9)',
      outlineOffset: 1,
    },
  } as const
}

export const viewerHudSx = {
  px: 0.8,
  py: 0.45,
  border: '1px solid rgba(255,255,255,0.18)',
  borderRadius: 1,
  backgroundColor: 'rgba(0,0,0,0.56)',
  backdropFilter: 'blur(8px)',
  pointerEvents: 'none',
} as const
