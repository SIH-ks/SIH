"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import { Crosshair } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";

export interface DiscrepancyMapProps {
  geometry: GeoJSON.Geometry | null;
  mismatchScore: number | null;
  parcelKey: string;
  neighbourGeometries?: GeoJSON.Geometry[];
}

/**
 * The parcel's cadastral polygon on a dark basemap, colored by mismatch severity,
 * with a genuine glow (MapLibre's `line-blur` paint property — not a CSS filter
 * hack) rather than a plain outline.
 *
 * Basemap: Esri's public "World Dark Gray Base" tile service, which needs no API
 * key or account — matters for a scaffold meant to run with zero external setup.
 * (CARTO's basemaps.cartocdn.com dark tiles, used here originally, now require a
 * registered API key and render an "API KEY REQUIRED" watermark without one — a
 * policy change on their end, not a MapLibre or app issue.) Esri's tile scheme
 * orders path segments `{z}/{y}/{x}` — swapped from the `{z}/{x}/{y}` XYZ
 * convention most other providers (including CARTO) use — so don't copy this URL
 * shape onto a different provider without checking its own tile scheme.
 */
export function DiscrepancyMap({ geometry, mismatchScore, parcelKey, neighbourGeometries = [] }: DiscrepancyMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [coords, setCoords] = useState<{ lng: number; lat: number } | null>(null);
  const [zoom, setZoom] = useState<number>(4);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          basemap: {
            type: "raster",
            tiles: [
              "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
            ],
            tileSize: 256,
            maxzoom: 16,
            attribution: "© Esri",
          },
          // Esri's dark basemap has no zoom level past 16; a reference/label layer
          // fills in road and place names on top at any zoom, including closer in.
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
          { id: "basemap", type: "raster", source: "basemap", paint: { "raster-opacity": 0.85 } },
          { id: "reference", type: "raster", source: "reference", paint: { "raster-opacity": 0.6 } },
        ],
      },
      center: [78.9629, 20.5937],
      zoom: 4,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    map.on("move", () => {
      const c = map.getCenter();
      setCoords({ lng: c.lng, lat: c.lat });
      setZoom(map.getZoom());
    });

    map.on("load", () => {
      if (geometry) {
        addParcelLayer(map, "subject", geometry, mismatchColor(mismatchScore), true);
        fitToGeometry(map, geometry);
      }
      neighbourGeometries.forEach((g, i) => addParcelLayer(map, `neighbour-${i}`, g, "#576269", false));
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded() || !geometry) return;
    removeParcelLayer(map, "subject");
    addParcelLayer(map, "subject", geometry, mismatchColor(mismatchScore), true);
    fitToGeometry(map, geometry);
  }, [geometry, mismatchScore]);

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-card">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div className="flex items-center gap-2">
          <Crosshair className="h-4 w-4 text-navy-700" />
          <span className="text-sm font-semibold text-slate-700">Geospatial Cross-Reference</span>
        </div>
        <span className="font-mono text-[11px] text-slate-400">Parcel {parcelKey}</span>
      </div>

      {/* The map canvas itself stays dark regardless of the surrounding page theme
          -- a dark basemap inside a light dashboard is the industry-standard look
          (Mapbox/Google dark map styles embedded in light admin panels), and the
          mismatch-colored glow reads better against it than against a light tile set. */}
      <div className="relative">
        <div ref={containerRef} className="h-[360px] w-full" />

        <div className="pointer-events-none absolute bottom-2 left-2 flex flex-col gap-0.5 rounded bg-black/60 px-2 py-1 font-mono text-[10px] text-emerald-300 backdrop-blur-sm">
          <span>LAT {coords ? coords.lat.toFixed(5) : "—"}</span>
          <span>LON {coords ? coords.lng.toFixed(5) : "—"}</span>
          <span>ZOOM {zoom.toFixed(1)}</span>
        </div>

        {!geometry && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/50">
            <span className="rounded-full bg-amber-400/90 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-amber-950">
              No cadastral geometry matched
            </span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-4 border-t border-slate-200 bg-slate-50 px-4 py-2.5 text-xs text-slate-500">
        {(
          [
            ["#10b981", "Within tolerance"],
            ["#f59e0b", "Minor / material"],
            ["#ef4444", "Severe"],
          ] as const
        ).map(([color, label]) => (
          <span key={label} className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

function mismatchColor(score: number | null): string {
  if (score === null) return "#576269";
  if (score <= 5) return "#3ecf8e";
  if (score <= 50) return "#f5a623";
  return "#ff4d5e";
}

function addParcelLayer(map: MapLibreMap, id: string, geometry: GeoJSON.Geometry, color: string, glow: boolean) {
  map.addSource(id, { type: "geojson", data: { type: "Feature", properties: {}, geometry } });
  map.addLayer({
    id: `${id}-fill`,
    type: "fill",
    source: id,
    paint: { "fill-color": color, "fill-opacity": glow ? 0.12 : 0.06 },
  });
  if (glow) {
    // Wide, blurred underlay line creates a genuine glow (MapLibre's line-blur),
    // with a crisp 1.5px line on top — the same layering trick used for neon UI.
    map.addLayer({
      id: `${id}-glow`,
      type: "line",
      source: id,
      paint: { "line-color": color, "line-width": 10, "line-blur": 8, "line-opacity": 0.55 },
    });
  }
  map.addLayer({
    id: `${id}-line`,
    type: "line",
    source: id,
    paint: { "line-color": color, "line-width": 1.5, "line-opacity": glow ? 1 : 0.5 },
  });
}

function removeParcelLayer(map: MapLibreMap, id: string) {
  for (const suffix of ["fill", "glow", "line"]) {
    if (map.getLayer(`${id}-${suffix}`)) map.removeLayer(`${id}-${suffix}`);
  }
  if (map.getSource(id)) map.removeSource(id);
}

function fitToGeometry(map: MapLibreMap, geometry: GeoJSON.Geometry) {
  const coords = collectCoordinates(geometry);
  if (coords.length === 0) return;
  const bounds = coords.reduce(
    (b, [lon, lat]) => b.extend([lon, lat]),
    new maplibregl.LngLatBounds(coords[0], coords[0]),
  );
  map.fitBounds(bounds, { padding: 48, maxZoom: 18, duration: 300 });
}

function collectCoordinates(geometry: GeoJSON.Geometry): [number, number][] {
  switch (geometry.type) {
    case "Polygon":
      return geometry.coordinates.flat() as [number, number][];
    case "MultiPolygon":
      return geometry.coordinates.flat(2) as [number, number][];
    default:
      return [];
  }
}
