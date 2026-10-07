// Bundle SVG artwork so updates use fresh content-based URLs (or inline data),
// rather than a cached public filename. Canvas, palette and picker share this.
const bundledIcons = import.meta.glob<string>("./assets/activity-icons/*.svg", {
  eager: true,
  query: "?url",
  import: "default",
});

export function activityIconUrl(asset: string): string {
  const filename = asset.includes(".") ? asset : `${asset}.png`;
  return bundledIcons[`./assets/activity-icons/${filename}`] || `/activity-icons/${filename}`;
}
