/** Return the absolute mobile offset that keeps an unshifted in-scene card in the viewport. */
export function markerCardHorizontalNudge(
  bounds: { left: number; right: number },
  viewportWidth: number,
  gutter = 16,
): number {
  const min = gutter;
  const max = viewportWidth - gutter;

  // The mobile CSS caps a card at this available width. Center a card only if a caller ever
  // hands us a wider box, so both edges move toward the readable area.
  if (bounds.right - bounds.left >= max - min) {
    return (min + max - bounds.left - bounds.right) / 2;
  }
  if (bounds.left < min) return min - bounds.left;
  if (bounds.right > max) return max - bounds.right;
  return 0;
}
