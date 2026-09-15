"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import { Layers, MapPin, Navigation } from "lucide-react";
import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { cn, formatArea } from "@/lib/format";
import type { ParcelGeoJson } from "@/types/parcel";

/**
 * The district-scale cadastral view: every matched parcel polygon on one map.
 *
 * This is the view that turns a list of records into a picture of a district. A
 * supervisor can see that the disagreements cluster in one taluk — information
 * no per-record screen can convey, and the reason a GIS layer belongs in a
 * land-records console rather than beside one.
 *
 * **Colouring is a choice the user makes, not one the map makes for them.**
 * Mismatch, workflow status and triage priority are three different questions,
 * and the same polygon means different things under each. Every mode ships a
 * legend, and the popup states the value in words, so hue is never the only
 * carrier of meaning.
 *
 * Colours are read once from the CSS custom properties at style-build time
 * rather than hard-coded: MapLibre paints into a canvas that Tailwind cannot
 * reach, so this is how the map stays inside the design system's palette in both
 * themes.
 */

type ColorMode = "mismatch" | "status" | "priority";

const MODES: { value: ColorMode; label: string; hint: string }[] = [
  { value: "mismatch", label: "Cadastral mismatch", hint: "Extracted area vs the matched polygon" },
  { value: "status", label: "Adjudication status", hint: "Where each record sits in the workflow" },
  { value: "priority", label: "Triage priority", hint: "Queue order the engine assigned" },
];

const LEGENDS: Record<ColorMode, { label: string; token: string }[]> = {
  mismatch: [
    { label: "Within tolerance (< 5)", token: "--status-good" },
    { label: "Minor / material (5–50)", token: "--status-warning" },
    { label: "Severe (≥ 50)", token: "--status-critical" },
    { label: "No score", token: "--ink-muted" },
  ],
  status: [
    { label: "Approved", token: "--status-good" },
    { label: "In review", token: "--series-1" },
    { label: "Escalated", token: "--status-serious" },
    { label: "Rejected", token: "--status-critical" },
    { label: "Pending triage", token: "--ink-muted" },
  ],
  priority: [
    { label: "Critical", token: "--status-critical" },
    { label: "High", token: "--status-serious" },
    { label: "Normal", token: "--status-warning" },
    { label: "Low", token: "--ink-muted" },
  ],
};

function token(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** A MapLibre data-driven paint expression per colour mode. Built at style time
 * from live token values so both themes get their own selected steps. */
function colorExpression(mode: ColorMode): maplibregl.ExpressionSpecification {
  const good = token("--status-good", "#0ca30c");
  const warning = token("--status-warning", "#fab219");
  const serious = token("--status-serious", "#ec835a");
  const critical = token("--status-critical", "#d03b3b");
  const muted = token("--ink-muted", "#7c8798");
  const series1 = token("--series-1", "#2a78d6");

  if (mode === "status") {
    return [
      "match",
      ["get", "review_status"],
      "approved", good,
      "in_review", series1,
      "escalated", serious,
      "rejected", critical,
      muted,
    ] as maplibregl.ExpressionSpecification;
  }
  if (mode === "priority") {
    return [
      "match",
      ["get", "priority"],
      "critical", critical,
      "high", serious,
      "normal", warning,
      muted,
    ] as maplibregl.ExpressionSpecification;
  }
  // `["has", …]` rather than comparing to null: MapLibre's typed expression union
  // has no null literal, and a parcel with no matched polygon genuinely has no
  // `mismatch_score` property rather than a null one.
  return [
    "case",
    ["!", ["has", "mismatch_score"]], muted,
    ["<", ["to-number", ["get", "mismatch_score"]], 5], good,
    ["<", ["to-number", ["get", "mismatch_score"]], 50], warning,
    critical,
  ] as maplibregl.ExpressionSpecification;
}

export function CadastralMap({
  collection,
  height = "h-[calc(100vh-260px)]",
}: {
  collection: ParcelGeoJson;
  height?: string;
}) {
  const router = useRouter();
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const [mode, setMode] = useState<ColorMode>("mismatch");
  const [ready, setReady] = useState(false);
  const [center, setCenter] = useState<{ lng: number; lat: number; zoom: number } | null>(null);

  const bounds = useMemo(() => boundsOf(collection), [collection]);

  const fitAll = useCallback(() => {
    if (map.current && bounds) map.current.fitBounds(bounds, { padding: 64, maxZoom: 13, duration: 600 });
  }, [bounds]);

  useEffect(() => {
    if (!container.current || map.current) return;

    const instance = new maplibregl.Map({
      container: container.current,
      style: {
        version: 8,
        sources: {
          basemap: {
            type: "raster",
            // Esri's public Canvas basemaps need no API key or account, which
            // matters for a system meant to run with zero external setup. Note the
            // {z}/{y}/{x} segment order — Esri's scheme, not the {z}/{x}/{y} XYZ
            // convention most other providers use. Do not copy this URL shape onto
            // a different provider without checking its own tile scheme.
            tiles: [
              "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
            ],
            tileSize: 256,
            maxzoom: 16,
            attribution: "© Esri",
          },
          reference: {
            type: "raster",
            tiles: [
              "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
            ],
            tileSize: 256,
            attribution: "© Esri",
          },
        },
        layers: [
          { id: "basemap", type: "raster", source: "basemap", paint: { "raster-opacity": 0.9 } },
          { id: "reference", type: "raster", source: "reference", paint: { "raster-opacity": 0.55 } },
        ],
      },
      center: [78.9629, 22.5937],
      zoom: 4.2,
      attributionControl: false,
    });
    map.current = instance;

    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    instance.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    instance.on("move", () => {
      const c = instance.getCenter();
      setCenter({ lng: c.lng, lat: c.lat, zoom: instance.getZoom() });
    });

    instance.on("load", () => {
      instance.addSource("parcels", { type: "geojson", data: collection as GeoJSON.FeatureCollection });

      instance.addLayer({
        id: "parcels-fill",
        type: "fill",
        source: "parcels",
        paint: { "fill-color": colorExpression("mismatch"), "fill-opacity": 0.34 },
      });
      // A wide, blurred underlay is a genuine glow (MapLibre's `line-blur`), which
      // is what makes a 40 m parcel findable at district zoom without inflating
      // the polygon itself and misrepresenting its extent.
      instance.addLayer({
        id: "parcels-glow",
        type: "line",
        source: "parcels",
        paint: {
          "line-color": colorExpression("mismatch"),
          "line-width": 9,
          "line-blur": 7,
          "line-opacity": 0.5,
        },
      });
      instance.addLayer({
        id: "parcels-line",
        type: "line",
        source: "parcels",
        paint: { "line-color": colorExpression("mismatch"), "line-width": 1.6 },
      });

      instance.on("mouseenter", "parcels-fill", () => {
        instance.getCanvas().style.cursor = "pointer";
      });
      instance.on("mouseleave", "parcels-fill", () => {
        instance.getCanvas().style.cursor = "";
      });

      instance.on("click", "parcels-fill", (event) => {
        const feature = event.features?.[0];
        if (!feature) return;
        const p = feature.properties as Record<string, string>;
        new maplibregl.Popup({ closeButton: true, maxWidth: "280px" })
          .setLngLat(event.lngLat)
          .setHTML(popupHtml(p))
          .addTo(instance);
      });

      if (bounds) instance.fitBounds(bounds, { padding: 64, maxZoom: 13, duration: 0 });
      setReady(true);
    });

    return () => {
      instance.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-paint on mode change. Repainting the existing layers rather than rebuilding
  // them keeps the viewport exactly where the user left it.
  useEffect(() => {
    const instance = map.current;
    if (!instance || !ready) return;
    const expression = colorExpression(mode);
    instance.setPaintProperty("parcels-fill", "fill-color", expression);
    instance.setPaintProperty("parcels-glow", "line-color", expression);
    instance.setPaintProperty("parcels-line", "line-color", expression);
  }, [mode, ready]);

  // Clicking a popup's "Open record" link navigates through the Next router
  // rather than a full page load. MapLibre injects the popup outside React's
  // tree, so the handler is delegated from the document.
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      const target = (event.target as HTMLElement)?.closest("[data-parcel-link]");
      if (!target) return;
      event.preventDefault();
      router.push(`/parcels/${target.getAttribute("data-parcel-link")}`);
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, [router]);

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface-card shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-ink-muted" aria-hidden />
          <span className="text-sm font-semibold text-ink-primary">Colour parcels by</span>
          <div className="flex rounded-lg border border-line p-0.5">
            {MODES.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setMode(option.value)}
                title={option.hint}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  mode === option.value
                    ? "bg-brand-navy text-white dark:bg-series-1"
                    : "text-ink-secondary hover:bg-surface-sunken",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <button
          type="button"
          onClick={fitAll}
          className="inline-flex items-center gap-1.5 rounded-lg border border-line-strong px-2.5 py-1.5 text-xs font-semibold text-ink-secondary transition-colors hover:bg-surface-sunken"
        >
          <Navigation className="h-3.5 w-3.5" aria-hidden /> Fit to data
        </button>
      </div>

      <div className="relative">
        {/* The canvas stays dark in both themes: a dark basemap makes the
            status-coloured polygons legible in a way a light tile set does not,
            and it is the established convention for an embedded GIS panel. */}
        <div ref={container} className={cn("w-full", height)} />

        {center && (
          <div className="pointer-events-none absolute bottom-3 left-3 flex flex-col gap-0.5 rounded-lg bg-black/65 px-2.5 py-1.5 font-mono text-[10px] text-emerald-300 backdrop-blur-sm">
            <span>LAT {center.lat.toFixed(5)}</span>
            <span>LON {center.lng.toFixed(5)}</span>
            <span>ZOOM {center.zoom.toFixed(1)}</span>
          </div>
        )}

        {collection.features.length === 0 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/55 px-6">
            <div className="max-w-sm rounded-xl bg-surface-card px-5 py-4 text-center shadow-pop">
              <MapPin className="mx-auto h-5 w-5 text-ink-muted" aria-hidden />
              <p className="mt-2 text-sm font-semibold text-ink-primary">No cadastral geometry to draw</p>
              <p className="mt-1 text-xs text-ink-secondary">
                {collection.properties.without_geometry} record
                {collection.properties.without_geometry === 1 ? " has" : "s have"} no matched polygon. A
                deployment with a cadastral GeoJSON source configured
                (<code className="font-mono">ADHIKAR_GEOMETRY_SOURCE_PATH</code>) would show them here.
              </p>
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4 border-t border-line bg-surface-sunken px-4 py-2.5">
        <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
          {LEGENDS[mode].map((entry) => (
            <li key={entry.label} className="flex items-center gap-1.5 text-xs text-ink-secondary">
              <span
                className="inline-block h-2.5 w-2.5 rounded-[3px]"
                style={{ background: `var(${entry.token})` }}
                aria-hidden
              />
              {entry.label}
            </li>
          ))}
        </ul>
        <p className="text-xs text-ink-muted">
          {collection.properties.returned} of {collection.properties.total_matching_filter} records drawn ·{" "}
          {collection.properties.without_geometry} without a matched polygon
        </p>
      </div>
    </div>
  );
}

function popupHtml(p: Record<string, string>): string {
  const area = p.area_sq_metre ? formatArea(Number(p.area_sq_metre)) : "—";
  const mismatch = p.mismatch_score !== undefined && p.mismatch_score !== null ? Number(p.mismatch_score).toFixed(1) : "—";
  const confidence =
    p.confidence_score !== undefined && p.confidence_score !== null
      ? `${Math.round(Number(p.confidence_score) * 100)}%`
      : "—";

  // Values are escaped before being interpolated: they originate from extracted
  // documents, and a village name containing a bracket must not become markup.
  return `
    <div style="font-family: Inter, system-ui, sans-serif; padding: 12px 14px;">
      <div style="font-size: 13px; font-weight: 700; color: var(--ink-primary);">${esc(p.village) || "Unknown village"}</div>
      <div style="font-size: 11px; color: var(--ink-muted); margin-top: 2px;">
        ${esc(p.district) || "—"} · Khata ${esc(p.khata_number) || "—"} · Survey ${esc(p.survey_number) || "—"}
      </div>
      <dl style="display:grid;grid-template-columns:auto auto;gap:4px 14px;margin:10px 0 0;font-size:11px;">
        <dt style="color: var(--ink-muted);">Area</dt><dd style="margin:0;font-weight:600;color:var(--ink-primary);">${area}</dd>
        <dt style="color: var(--ink-muted);">Mismatch</dt><dd style="margin:0;font-weight:600;color:var(--ink-primary);">${mismatch}</dd>
        <dt style="color: var(--ink-muted);">Confidence</dt><dd style="margin:0;font-weight:600;color:var(--ink-primary);">${confidence}</dd>
        <dt style="color: var(--ink-muted);">Status</dt><dd style="margin:0;font-weight:600;color:var(--ink-primary);">${esc(p.review_status).replace("_", " ")}</dd>
        <dt style="color: var(--ink-muted);">Findings</dt><dd style="margin:0;font-weight:600;color:var(--ink-primary);">${esc(p.issue_count) || "0"}</dd>
      </dl>
      <a href="/parcels/${esc(p.parcel_id)}" data-parcel-link="${esc(p.parcel_id)}"
         style="display:inline-block;margin-top:10px;font-size:12px;font-weight:600;color:var(--series-1);text-decoration:none;">
        Open record →
      </a>
    </div>`;
}

function esc(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value).replace(/[&<>"']/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] ?? char,
  );
}

function boundsOf(collection: ParcelGeoJson): maplibregl.LngLatBoundsLike | null {
  const points: [number, number][] = [];
  for (const feature of collection.features) {
    points.push(...collectCoordinates(feature.geometry));
  }
  if (points.length === 0) return null;
  const bounds = new maplibregl.LngLatBounds(points[0], points[0]);
  for (const point of points) bounds.extend(point);
  return bounds;
}

function collectCoordinates(geometry: GeoJSON.Geometry): [number, number][] {
  switch (geometry.type) {
    case "Polygon":
      return geometry.coordinates.flat() as [number, number][];
    case "MultiPolygon":
      return geometry.coordinates.flat(2) as [number, number][];
    case "Point":
      return [geometry.coordinates as [number, number]];
    default:
      return [];
  }
}
