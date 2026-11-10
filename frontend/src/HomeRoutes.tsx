import { useEffect, useRef, useState } from "react";

const paths = {
  api: "M300 101 C345 110 360 225 414 276",
  sap: "M300 288.4 C340 288 370 300 410 304",
  manhattan: "M300 505.1 C355 495 370 395 430 356",
  cloud: "M700 101 C655 110 640 225 586 276",
  kafka: "M700 288.4 C660 288 630 300 590 304",
  pubsub: "M700 505.1 C645 495 630 395 570 356",
  website: "M500 62.5 C500 130 490 190 500 222",
  rabbit: "M500 554.5 C500 485 510 430 500 398",
};

const packets = [
  { route: "api", direction: "in", duration: 3700, offset: 1200 },
  { route: "sap", direction: "out", duration: 4800, offset: 3100 },
  { route: "manhattan", direction: "in", duration: 5400, offset: 600 },
  { route: "cloud", direction: "out", duration: 3900, offset: 2400 },
  { route: "kafka", direction: "in", duration: 3200, offset: 1700 },
  { route: "kafka", direction: "out", duration: 5800, offset: 4600 },
  { route: "pubsub", direction: "out", duration: 4400, offset: 900 },
  { route: "website", direction: "in", duration: 4600, offset: 2200 },
  { route: "rabbit", direction: "in", duration: 5100, offset: 3800 },
  { route: "api", direction: "out", duration: 6200, offset: 4900 },
  { route: "manhattan", direction: "out", duration: 6700, offset: 2800 },
  { route: "cloud", direction: "in", duration: 5900, offset: 5200 },
  { route: "pubsub", direction: "in", duration: 6400, offset: 3600 },
  { route: "website", direction: "out", duration: 5300, offset: 4100 },
];

const reducedMotionQuery = "(prefers-reduced-motion: reduce)";
const preferenceKey = "mina-home-route-animation";

export default function HomeRoutes() {
  const svg = useRef<SVGSVGElement>(null);
  const [reducedMotion, setReducedMotion] = useState(() => matchMedia(reducedMotionQuery).matches);
  const [preference, setPreference] = useState<boolean | null>(() => {
    const saved = localStorage.getItem(preferenceKey);
    return saved === "play" ? true : saved === "pause" ? false : null;
  });
  const playing = preference ?? !reducedMotion;

  useEffect(() => {
    const query = matchMedia(reducedMotionQuery);
    const update = () => setReducedMotion(query.matches);
    query.addEventListener("change", update);
    update();
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (!playing || !svg.current) return;
    const root = svg.current;
    const routes = new Map(Array.from(root.querySelectorAll<SVGPathElement>("path[data-route]"), path =>
      [path.dataset.route, { path, length: path.getTotalLength() }]));
    const circles = Array.from(root.querySelectorAll<SVGCircleElement>(".flow-packet"));
    const animations = packets.flatMap((packet, index) => {
      const route = routes.get(packet.route);
      return route ? [{ ...packet, ...route, circle: circles[index] }] : [];
    });
    const started = performance.now();
    let frame: number;

    // Updating SVG coordinates uses the same path geometry with software rendering.
    const draw = (now: number) => {
      for (const { path, length, direction, duration, offset, circle } of animations) {
        const progress = ((now - started + offset) % duration) / duration;
        const point = path.getPointAtLength(length * (direction === "out" ? 1 - progress : progress));
        circle.setAttribute("cx", String(point.x));
        circle.setAttribute("cy", String(point.y));
        circle.setAttribute("opacity", String(.95 * Math.min(1, progress / .12, (1 - progress) / .14)));
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [playing]);

  return <>
    <svg ref={svg} className="mina-routes" data-playing={playing} viewBox="0 0 1000 620" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="home-route" x1="0" x2="1">
          <stop offset="0" stopColor="#38d8ff"/><stop offset=".5" stopColor="#7b75ff"/><stop offset="1" stopColor="#43e6a8"/>
        </linearGradient>
        <filter id="home-glow-filter"><feGaussianBlur stdDeviation="4" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      </defs>
      {Object.entries(paths).map(([route, path]) => <path key={route} data-route={route} d={path}/>)}
      {playing && packets.map(({ route, direction }, index) => (
        <circle key={`${route}-${direction}`} r={index % 3 === 0 ? 5.5 : 4.2}
          className={`flow-packet ${direction}`} opacity={0}/>
      ))}
    </svg>
    <div className="live-indicator">
      {playing && <i aria-hidden="true"/>} LIVE MINA
      <button type="button" onClick={() => {
        localStorage.setItem(preferenceKey, playing ? "pause" : "play");
        setPreference(!playing);
      }}>
        {playing ? "Pause route animation" : "Play route animation"}
      </button>
    </div>
  </>;
}
