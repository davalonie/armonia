// Album lists as in the app: the server names the album that collects loose songs («Singles», X-Armonia-Albums) and
// it is not shown as an album in Albumes or Inicio. Its songs stay in Canciones, playlists and search.
import {library} from './api.js';

export function withoutDefaultAlbum(page) {
  const albums = page?.album || [];
  return page?.defaultAlbum ? albums.filter(a => a.name !== page.defaultAlbum) : albums;
}

/** getAlbumList2 without the default album; one more is asked for so short rows keep their size. */
export async function albumList(params) {
  const size = Number(params.size) || 0;
  const r = await library('getAlbumList2', size ? {...params, size: size + 1} : params, {headers: {'X-Armonia-Albums': '1'}});
  const albums = withoutDefaultAlbum(r.albumList2);
  return size ? albums.slice(0, size) : albums;
}
