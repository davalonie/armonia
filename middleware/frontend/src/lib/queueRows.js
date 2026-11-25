// The phone's queue sheet, as the app's QueueSheet: rows from the current song on, in the order
// they will play, each with its real queue index and a key that survives repeated songs.

/** Port of visibleQueueRows() (ui/player/QueueSheet.kt). */
export function visibleQueueRows(ids, order, current) {
  const seen = new Map();
  const keys = ids.map(id => { const n = seen.get(id) || 0; seen.set(id, n + 1); return `${n}:${id}`; });
  return order.slice(Math.max(0, order.indexOf(current)))
    .filter(index => keys[index] !== undefined).map(index => ({index, key: keys[index]}));
}

/** Where a row dragged `dy` px from position `from` lands: it passes a neighbour at half its height. */
export function dropPosition(from, dy, height, count) {
  if (!height || count < 1) return from;
  return Math.max(0, Math.min(count - 1, from + Math.round(dy / height)));
}

/** How far the row at `position` steps aside while another goes from `from` to `to`. */
export function stepAside(position, from, to, height) {
  if (from < to && position > from && position <= to) return -height;
  if (from > to && position >= to && position < from) return height;
  return 0;
}
