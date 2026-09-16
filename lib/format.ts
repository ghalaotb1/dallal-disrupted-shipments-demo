export const fmtSar = (n: number) => `SAR ${n.toLocaleString("en-US")}`;
export const fmtKm = (m: number) => (m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(m < 10_000 ? 1 : 0)} km`);
export const pct = (n: number) => `${Math.round(n * 100)}%`;
export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
export const clamp = (n: number, min: number, max: number) => Math.min(max, Math.max(min, n));
