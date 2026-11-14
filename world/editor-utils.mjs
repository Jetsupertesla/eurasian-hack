// Geometry shared by the viewer and offline tests. R has columns right, down, forward.
export function coneVertices(view, fallbackDistance = 2) {
  const origin = view.pos || [0, 0, 0];
  const R = view.R;
  if (!R || R.length !== 3) return [];
  const depth = Math.max(.15, Math.min(view.dist || fallbackDistance, 30));
  const k = Math.tan((view.fov || 62) * Math.PI / 360);
  const aspect = view.aspect || 1;
  const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([x, y]) => {
    const local = [x * k * aspect * depth, y * k * depth, depth];
    return origin.map((v, row) => v + R[row].reduce((sum, value, col) => sum + value * local[col], 0));
  });
  return corners.flatMap((corner, i) => [...origin, ...corner, ...corner, ...corners[(i + 1) % 4]]);
}
