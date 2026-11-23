// Formats of «Historial y estadisticas», the same as the app's ListeningScreen.

/** «45 min» or «3 h 12 min». */
export function listenTime(seconds) {
  const minutes = Math.floor((Number(seconds) || 0) / 60);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

const localDate = iso => {
  const [y, m, d] = String(iso || '').slice(0, 10).split('-').map(Number);
  return y && m && d ? new Date(y, m - 1, d) : null;
};
const clean = text => text.replace(/\./g, '').replace(/ de /g, ' ');

/** First and last day of the chart: «21 oct», «17 nov 2025», or «nov 2025» for Siempre. */
export function chartDate(iso, period) {
  const date = localDate(iso);
  if (!date) return '';
  const options = period === 'week' || period === 'month' ? {day: 'numeric', month: 'short'}
    : period === 'year' ? {day: 'numeric', month: 'short', year: 'numeric'} : {month: 'short', year: 'numeric'};
  return clean(date.toLocaleDateString('es-ES', options));
}

/** «hoy 18:05», «ayer 09:30» or «12 nov». `at` in seconds. */
export function whenHeard(at, now = new Date()) {
  const date = new Date(at * 1000);
  const day = d => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  const time = date.toLocaleTimeString('es-ES', {hour: '2-digit', minute: '2-digit', hour12: false});
  if (day(date) === day(now)) return `hoy ${time}`;
  if (day(date) === day(yesterday)) return `ayer ${time}`;
  return clean(date.toLocaleDateString('es-ES', {day: 'numeric', month: 'short'}));
}
