import { useEffect, useState } from "react";
import "./font-controls.css";

function readSize(key: string, fallback: number, min: number, max: number) {
  const stored = localStorage.getItem(key);
  const value = stored === null ? fallback : Number(stored);
  return Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : fallback;
}

// Preserve each component's typography while scaling fixed pixel fonts too.
function scaledRules(rules: CSSRuleList): string {
  return Array.from(rules).map((rule) => {
    if (rule instanceof CSSStyleRule) {
      const size = rule.style.fontSize;
      return /^\d+(\.\d+)?px$/.test(size)
        ? `${rule.selectorText}{font-size:var(--configuration-font-override, calc(${size} * var(--studio-font-scale, 1))) !important;}` : "";
    }
    if (rule instanceof CSSMediaRule || rule instanceof CSSSupportsRule) {
      return `${rule.cssText.slice(0, rule.cssText.indexOf("{"))}{${scaledRules(rule.cssRules)}}`;
    }
    return "";
  }).join("\n");
}

export function useFontPreferences() {
  const [screenFont, setScreenFont] = useState(() => readSize("mina-screen-font", 100, 75, 150));
  const [configFont, setConfigFont] = useState(() => readSize("mina-config-font", 11, 9, 18));
  useEffect(() => {
    const style = document.createElement("style");
    style.dataset.studioFontScaling = "true";
    style.textContent = Array.from(document.styleSheets).map((sheet) => {
      try { return scaledRules(sheet.cssRules); } catch { return ""; }
    }).join("\n") + `
      .config, .input-mapper-backdrop, .mapper-backdrop { --configuration-font-override: var(--configuration-font-size, 11px); font-size:var(--configuration-font-size, 11px) !important; }
      :is(.config, .input-mapper-backdrop, .mapper-backdrop) :is(div, span, label, input, select, textarea, button, p, code, pre, b, strong, em, summary, td, th, li, a, h1, h2, h3, h4, small) {
        font-size:var(--configuration-font-size, 11px) !important;
      }
    `;
    document.head.appendChild(style);
    return () => style.remove();
  }, []);
  useEffect(() => {
    document.documentElement.style.setProperty("--studio-font-scale", String(screenFont / 100));
    document.documentElement.style.setProperty("--configuration-font-size", `${configFont}px`);
    localStorage.setItem("mina-screen-font", String(screenFont));
    localStorage.setItem("mina-config-font", String(configFont));
  }, [screenFont, configFont]);
  return { screenFont, setScreenFont, configFont, setConfigFont };
}

export function FontControl({ scope, value, onChange }: { scope: "Screen" | "Configuration"; value: number; onChange: (value: number) => void }) {
  const screen = scope === "Screen";
  return <label className="font-control" title={screen ? "Font size across the screen; configuration has its own setting" : "Font size for all configuration tabs and the expanded input editor"}>
    <span>{screen ? "Screen font" : "Panel font"}</span>
    <select aria-label={`${scope} font size`} value={value} onChange={(event) => onChange(Number(event.target.value))}>
      {(screen ? [75, 85, 100, 115, 130, 150] : [9, 10, 11, 12, 13, 14, 16, 18]).map((size) => <option key={size} value={size}>{size}{screen ? "%" : " px"}{size === (screen ? 100 : 11) ? " (default)" : ""}</option>)}
    </select>
  </label>;
}
