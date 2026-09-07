"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import { useEffect, useRef, useState } from "react";
import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";

import { IconTarget } from "./icons";

export interface DiscrepancyMapProps {
  geometry: GeoJSON.Geometry | null;
  mismatchScore: number | null;
  parcelKey: string;
  neighbourGeometries?: GeoJSON.Geometry[];
}

/**
 * The parcel's cadastral polygon on a dark basemap, colored by mismatch severity,
 * with a genuine glow (MapLibre's `line-blur` paint property — not a CSS filter
 * hack) rather than a plain outline. CartoDB's "dark matter" raster tiles are used
 * because they need no API key, which matters for a scaffold meant to run with zero
 * external account setup.
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
            tiles: ["https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors © CARTO",
          },
        },
        layers: [{ id: "basemap", type: "raster", source: "basemap", paint: { "raster-opacity": 0.85 } }],
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
    <div className="hud-corners relative border border-seam bg-hull text-signal-cyan">
      <span className="corner-tl" />
      <span className="corner-br" />
      <div className="flex items-center justify-between border-b border-seam bg-plate px-3.5 py-2">
        <div className="flex items-center gap-2">
          <IconTarget className="h-3.5 w-3.5 text-signal-cyan" />
          <span className="font-display text-xs font-semibold uppercase tracking-wide text-ink-primary">
            Geospatial Cross-Reference
          </span>
        </div>
        <span className="font-mono text-[10px] text-ink-dim">PARCEL {parcelKey}</span>
      </div>

      <div className="relative">
        <div ref={containerRef} className="h-[420px] w-full" />

        {/* telemetry overlay — coordinates + zoom, styled like a map HUD readout */}
        <div className="pointer-events-none absolute bottom-2 left-2 flex flex-col gap-0.5 bg-void/70 px-2 py-1 font-mono text-[10px] text-signal-cyan backdrop-blur-sm">
          <span>LAT {coords ? coords.lat.toFixed(5) : "—"}</span>
          <span>LON {coords ? coords.lng.toFixed(5) : "—"}</span>
          <span>ZOOM {zoom.toFixed(1)}</span>
        </div>

        {!geometry && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-void/60">
            <span className="border border-signal-amber/40 bg-signal-amber/10 px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-signal-amber">
              No cadastral geometry matched
            </span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-4 border-t border-seam bg-plate px-3.5 py-2 font-mono text-[10px] text-ink-dim">
        {(
          [
            ["#3ecf8e", "Within tolerance"],
            ["#f5a623", "Minor / material"],
            ["#ff4d5e", "Severe"],
          ] as const
        ).map(([color, label]) => (
          <span key={label} className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5" style={{ backgroundColor: color, boxShadow: `0 0 6px ${color}` }} />
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
