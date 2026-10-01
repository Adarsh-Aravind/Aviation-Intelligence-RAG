"use client";

// Decorative background: live flights around India, each drawn as its origin → destination great-circle
// route with a small plane and its airport codes. No map — deliberately faint so it never competes with
// the content. Data comes from the backend's /flights snapshot; between refreshes each plane is moved
// along its route at its reported ground speed.
import { useEffect, useRef } from "react";

import { api } from "@/lib/api";
import type { Flight } from "@/lib/types";

// Framed on India (the backend polls a slightly larger box: flights.py REGION). Routes to or from
// farther airports simply run off the edge of the screen.
const BOX = { latMin: 5, latMax: 37, lonMin: 64, lonMax: 98 };
const LAT_C = (BOX.latMin + BOX.latMax) / 2;
const LON_C = (BOX.lonMin + BOX.lonMax) / 2;
const KX = Math.cos((LAT_C * Math.PI) / 180); // equirectangular with true scale at mid-latitude

const ACCENT = "56, 189, 248"; // --accent
const PLANE = "230, 237, 247"; // --text
const POLL_MS = 120_000;
const WARMUP_RETRY_MS = 15_000; // the server's feed fills ~10 s after the first request
const FRAME_MS = 3_000; // real-time motion at this zoom is a fraction of a pixel per second
const FADE_MS = 1_500;
const SEGMENTS = 64;
const LABEL_MIN_WIDTH = 640; // on phones the labels would sit behind body text, so only planes are drawn

// Top-down airliner silhouette, nose pointing up (−y), about 13 px long.
const PLANE_ICON =
  "M0 -6.5 L0.9 -5.2 L0.9 -1.6 L6 1.2 L6 2.3 L0.9 0.6 L0.7 4.2 L2.6 5.6 L2.6 6.4 L0 5.8 " +
  "L-2.6 6.4 L-2.6 5.6 L-0.7 4.2 L-0.9 0.6 L-6 2.3 L-6 1.2 L-0.9 -1.6 L-0.9 -5.2 Z";
const EARTH_KM = 6371;
const MAX_ELAPSED_MS = 30 * 60_000; // guards against a badly skewed client clock

type Vec3 = [number, number, number];

interface Track {
  label: string; // "DEL → BOM"
  path: [number, number][]; // [lat, lon] samples along the great circle, longitudes unwrapped
  a: Vec3;
  b: Vec3;
  omega: number; // central angle origin → destination
  f0: number; // fraction flown at updatedAt
  perMs: number; // fraction per millisecond at reported ground speed
  updatedAt: number;
  bornAt: number;
  dyingAt: number | null;
}

const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

function toVec(lat: number, lon: number): Vec3 {
  const p = rad(lat);
  const l = rad(lon);
  return [Math.cos(p) * Math.cos(l), Math.cos(p) * Math.sin(l), Math.sin(p)];
}

function angle(a: Vec3, b: Vec3): number {
  const dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  return Math.acos(Math.min(1, Math.max(-1, dot)));
}

function slerp(a: Vec3, b: Vec3, omega: number, t: number): [number, number] {
  const s = Math.sin(omega);
  const wa = Math.sin((1 - t) * omega) / s;
  const wb = Math.sin(t * omega) / s;
  const x = wa * a[0] + wb * b[0];
  const y = wa * a[1] + wb * b[1];
  const z = wa * a[2] + wb * b[2];
  return [deg(Math.atan2(z, Math.hypot(x, y))), deg(Math.atan2(y, x))];
}

function unwrap(lon: number, prev: number): number {
  while (lon - prev > 180) lon -= 360;
  while (lon - prev < -180) lon += 360;
  return lon;
}

function buildTrack(f: Flight, updatedAt: number, now: number, prev?: Track): Track | null {
  const a = toVec(f.origin.lat, f.origin.lon);
  const b = toVec(f.destination.lat, f.destination.lon);
  const omega = angle(a, b);
  if (omega < 1e-3) return null;
  const path: [number, number][] = [];
  for (let i = 0; i <= SEGMENTS; i++) {
    const [lat, lon] = slerp(a, b, omega, i / SEGMENTS);
    path.push([lat, i === 0 ? unwrap(lon, LON_C) : unwrap(lon, path[i - 1][1])]);
  }
  const pos = toVec(f.lat, f.lon);
  const flown = angle(a, pos);
  const left = angle(pos, b);
  return {
    label: `${f.origin.iata} → ${f.destination.iata}`,
    path,
    a,
    b,
    omega,
    f0: flown / (flown + left || 1),
    perMs: f.velocity / 1000 / 1000 / (omega * EARTH_KM),
    updatedAt,
    bornAt: prev?.bornAt ?? now,
    dyingAt: null,
  };
}

export function FlightBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const planeIcon = new Path2D(PLANE_ICON); // browser-only API, so built here rather than at import
    const fontFamily = getComputedStyle(document.documentElement).getPropertyValue("--font-jetbrains") || "monospace";
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const tracks = new Map<string, Track>();
    let width = 0;
    let height = 0;
    let scale = 1;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let raf: number | undefined;
    let lastFetch = 0;
    let stopped = false;

    const project = (lat: number, lon: number): [number, number] => [
      width / 2 + (lon - LON_C) * KX * scale,
      height / 2 - (lat - LAT_C) * scale,
    ];

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // Between "contain" and "cover": the whole region reads as one very zoomed-out view on desktop,
      // and phones still get a useful slice rather than a tiny strip.
      const contain = Math.min(width / ((BOX.lonMax - BOX.lonMin) * KX), height / (BOX.latMax - BOX.latMin));
      const cover = Math.max(width / ((BOX.lonMax - BOX.lonMin) * KX), height / (BOX.latMax - BOX.latMin));
      scale = Math.sqrt(contain * cover);
    };

    const opacity = (t: Track, now: number) => {
      if (reduceMotion) return t.dyingAt === null ? 1 : 0;
      const fadeIn = Math.min(1, (now - t.bornAt) / FADE_MS);
      const fadeOut = t.dyingAt === null ? 1 : Math.max(0, 1 - (now - t.dyingAt) / FADE_MS);
      return fadeIn * fadeOut;
    };

    const strokePath = (points: [number, number][]) => {
      ctx.beginPath();
      points.forEach(([lat, lon], i) => {
        const [x, y] = project(lat, lon);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    };

    /** Draws one frame; returns true while something is fading (needs smooth frames). */
    const draw = (now: number): boolean => {
      ctx.clearRect(0, 0, width, height);
      ctx.font = `500 9px ${fontFamily}`;
      ctx.textBaseline = "middle";
      const labels: [number, number, number, number][] = []; // drawn label boxes, to avoid overlaps
      let animating = false;
      for (const [key, t] of tracks) {
        const elapsed = Math.min(Math.max(0, now - t.updatedAt), MAX_ELAPSED_MS);
        const f = Math.min(1, t.f0 + elapsed * t.perMs);
        if (f >= 1 && t.dyingAt === null) t.dyingAt = now; // landed — fade away
        const m = opacity(t, now);
        if (t.dyingAt !== null && m <= 0) {
          tracks.delete(key);
          continue;
        }
        if (m < 1) animating = true;

        const split = Math.max(1, Math.round(f * SEGMENTS));
        const [lat, lon] = slerp(t.a, t.b, t.omega, f);
        const here: [number, number] = [lat, unwrap(lon, t.path[split - 1][1])];

        ctx.lineWidth = 1;
        ctx.setLineDash([]);
        ctx.strokeStyle = `rgba(${ACCENT}, ${0.1 * m})`;
        strokePath([...t.path.slice(0, split), here]);
        ctx.setLineDash([2, 5]);
        ctx.strokeStyle = `rgba(${ACCENT}, ${0.05 * m})`;
        strokePath([here, ...t.path.slice(split)]);
        ctx.setLineDash([]);

        ctx.fillStyle = `rgba(${ACCENT}, ${0.12 * m})`;
        for (const [plat, plon] of [t.path[0], t.path[SEGMENTS]]) {
          const [x, y] = project(plat, plon);
          ctx.beginPath();
          ctx.arc(x, y, 1.5, 0, Math.PI * 2);
          ctx.fill();
        }

        // Plane glyph pointing along the route.
        const [x, y] = project(here[0], here[1]);
        const [nlat, nlon] = slerp(t.a, t.b, t.omega, Math.min(1, f + 0.002));
        const [nx, ny] = project(nlat, unwrap(nlon, here[1]));
        const heading = Math.atan2(ny - y, nx - x);
        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(heading + Math.PI / 2);
        ctx.fillStyle = `rgba(${PLANE}, ${0.42 * m})`;
        ctx.fill(planeIcon);
        ctx.restore();

        // Route label beside the plane, skipped where it would overlap another one.
        const w = ctx.measureText(t.label).width;
        const box: [number, number, number, number] = [x + 9, y - 6, w, 12];
        const clear = labels.every(
          ([bx, by, bw, bh]) => box[0] > bx + bw || box[0] + box[2] < bx || box[1] > by + bh || box[1] + box[3] < by,
        );
        if (width >= LABEL_MIN_WIDTH && clear && x > 0 && x < width && y > 0 && y < height) {
          labels.push(box);
          ctx.fillStyle = `rgba(${PLANE}, ${0.32 * m})`;
          ctx.fillText(t.label, box[0], y);
        }
      }
      return animating;
    };

    const schedule = () => {
      if (stopped || document.visibilityState !== "visible") return;
      clearTimeout(timer);
      if (raf !== undefined) cancelAnimationFrame(raf);
      raf = undefined;
      const animating = draw(Date.now());
      if (animating) raf = requestAnimationFrame(schedule);
      else timer = setTimeout(schedule, FRAME_MS);
    };

    const load = async () => {
      lastFetch = Date.now();
      try {
        const data = await api.flights();
        if (stopped) return;
        if (!data.updated_at || data.flights.length === 0) {
          clearTimeout(retry);
          retry = setTimeout(() => void load(), WARMUP_RETRY_MS);
          return;
        }
        const updatedAt = Date.parse(data.updated_at);
        const now = Date.now();
        const seen = new Set<string>();
        for (const f of data.flights) {
          const track = buildTrack(f, updatedAt, now, tracks.get(f.callsign));
          if (!track) continue;
          seen.add(f.callsign);
          tracks.set(f.callsign, track);
        }
        for (const [key, t] of tracks) if (!seen.has(key) && t.dyingAt === null) t.dyingAt = now;
        schedule();
      } catch {
        // Purely decorative: keep whatever is already on screen.
      }
    };

    const onVisibility = () => {
      if (document.visibilityState !== "visible") return;
      if (Date.now() - lastFetch >= POLL_MS) void load();
      schedule();
    };
    const onResize = () => {
      resize();
      schedule();
    };

    resize();
    void load();
    const poll = setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, POLL_MS);
    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stopped = true;
      clearInterval(poll);
      clearTimeout(timer);
      clearTimeout(retry);
      if (raf !== undefined) cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return <canvas ref={canvasRef} aria-hidden className="pointer-events-none fixed inset-0 -z-10 h-full w-full" />;
}
