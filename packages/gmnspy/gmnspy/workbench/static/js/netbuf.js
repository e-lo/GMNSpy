// Decode the binary network payload from /network.bin (layout: gmnspy.viz.buffers.pack_network).
export function widthForLanes(lanes) { return Math.max(1.2, Math.min(9, 0.9 + 0.8 * lanes)); }

const take = (buf, off, bytes, Ctor) => new Ctor(buf.slice(off, off + bytes));

function buildArrows(L, linkStart, P) {
  const arrows = [];
  for (let i = 0; i < L.count; i++) {
    const s = linkStart[i], e = linkStart[i + 1];
    if (e - s < 2) continue;
    const m = Math.max(s + 1, Math.floor((s + e) / 2));
    const x1 = P[(m - 1) * 2], y1 = P[(m - 1) * 2 + 1], x2 = P[m * 2], y2 = P[m * 2 + 1];
    arrows.push({ position: [(x1 + x2) / 2, (y1 + y2) / 2], angle: -Math.atan2(x2 - x1, y2 - y1) * 180 / Math.PI });
  }
  return arrows;
}

export function decodeNetwork(buf) {
  const hlen = new DataView(buf).getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hlen)));
  const L = header.links, N = header.nodes;
  let off = 4 + hlen;
  const linkPositions = take(buf, off, L.positionsBytes, Float32Array); off += L.positionsBytes;
  const linkStart = take(buf, off, L.startIndicesBytes, Uint32Array); off += L.startIndicesBytes;
  const linkIds = take(buf, off, L.idsBytes, Float64Array); off += L.idsBytes;
  const linkLanes = take(buf, off, L.lanesBytes, Uint8Array); off += L.lanesBytes;
  const nodePositions = take(buf, off, N.positionsBytes, Float32Array); off += N.positionsBytes;
  const nodeIds = take(buf, off, N.idsBytes, Float64Array);
  const id2idx = new Map(), nodeId2idx = new Map();
  for (let i = 0; i < linkIds.length; i++) id2idx.set(linkIds[i], i);
  for (let i = 0; i < nodeIds.length; i++) nodeId2idx.set(nodeIds[i], i);
  const linkWidths = new Float32Array(linkStart[L.count]);
  for (let i = 0; i < L.count; i++) {
    const w = widthForLanes(linkLanes[i]);
    for (let v = linkStart[i]; v < linkStart[i + 1]; v++) linkWidths[v] = w;
  }
  return {
    L, N, linkPositions, linkStart, linkIds, linkLanes, linkWidths, nodePositions, nodeIds, id2idx, nodeId2idx,
    arrows: buildArrows(L, linkStart, linkPositions),
  };
}
