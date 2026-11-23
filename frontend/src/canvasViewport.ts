export type CanvasPoint = { x: number; y: number };
type CanvasSize = { width: number; height: number };
type Bounds = { left: number; top: number; right: number; bottom: number };

export const MAX_CANVAS_ZOOM = 1.5;
export const MIN_MANUAL_CANVAS_ZOOM = 0.1;

export function fitCanvasView(bounds: Bounds[], viewport: CanvasSize, maxZoom: number) {
  if (!viewport.width || !viewport.height || !bounds.length) return;
  const area = bounds.reduce((combined, item) => ({
    left: Math.min(combined.left, item.left),
    top: Math.min(combined.top, item.top),
    right: Math.max(combined.right, item.right),
    bottom: Math.max(combined.bottom, item.bottom),
  }));
  const margin = Math.min(24, viewport.width / 8, viewport.height / 8);
  return {
    center: { x: (area.left + area.right) / 2, y: (area.top + area.bottom) / 2 },
    zoom: Math.min(maxZoom,
      (viewport.width - 2 * margin) / Math.max(1, area.right - area.left),
      (viewport.height - 2 * margin) / Math.max(1, area.bottom - area.top)),
  };
}

export function centeredCanvasScroll(center: CanvasPoint, viewport: CanvasSize, zoom: number) {
  return {
    left: Math.max(0, center.x * zoom - viewport.width / 2),
    top: Math.max(0, center.y * zoom - viewport.height / 2),
  };
}
