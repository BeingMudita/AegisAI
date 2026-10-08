import { useEffect, useRef } from "react";

/**
 * A quiet, animated node-and-line field painted behind the whole app. It reads
 * the --plexus token (an "r, g, b" triple) so the same canvas looks right in
 * both themes, stays at a very low opacity so data never competes with it, and
 * renders a single static frame when the viewer prefers reduced motion.
 */
export function Backdrop() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    let width = 0;
    let height = 0;
    let dpr = 1;

    type Node = { x: number; y: number; vx: number; vy: number };
    let nodes: Node[] = [];

    const rgb = () =>
      getComputedStyle(document.documentElement).getPropertyValue("--plexus").trim() || "140, 160, 200";

    function seed() {
      // Density scales with area but is capped so large screens stay cheap.
      const target = Math.min(90, Math.round((width * height) / 22000));
      nodes = Array.from({ length: target }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.18,
        vy: (Math.random() - 0.5) * 0.18,
      }));
    }

    function resize() {
      dpr = Math.min(2, window.devicePixelRatio || 1);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas!.width = width * dpr;
      canvas!.height = height * dpr;
      canvas!.style.width = `${width}px`;
      canvas!.style.height = `${height}px`;
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
      seed();
    }

    function draw() {
      const color = rgb();
      ctx!.clearRect(0, 0, width, height);
      const linkDist = 150;
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const d = Math.hypot(dx, dy);
          if (d < linkDist) {
            const alpha = (1 - d / linkDist) * 0.14;
            ctx!.strokeStyle = `rgba(${color}, ${alpha})`;
            ctx!.lineWidth = 1;
            ctx!.beginPath();
            ctx!.moveTo(a.x, a.y);
            ctx!.lineTo(b.x, b.y);
            ctx!.stroke();
          }
        }
      }
      for (const n of nodes) {
        ctx!.fillStyle = `rgba(${color}, 0.5)`;
        ctx!.beginPath();
        ctx!.arc(n.x, n.y, 1.3, 0, Math.PI * 2);
        ctx!.fill();
      }
    }

    let raf = 0;
    function tick() {
      for (const n of nodes) {
        n.x += n.vx;
        n.y += n.vy;
        if (n.x < 0 || n.x > width) n.vx *= -1;
        if (n.y < 0 || n.y > height) n.vy *= -1;
      }
      draw();
      raf = requestAnimationFrame(tick);
    }

    function start() {
      cancelAnimationFrame(raf);
      resize();
      if (reduce.matches) draw();
      else tick();
    }

    start();
    const onResize = () => {
      cancelAnimationFrame(raf);
      resize();
      if (reduce.matches) draw();
      else tick();
    };
    window.addEventListener("resize", onResize);
    reduce.addEventListener("change", start);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      reduce.removeEventListener("change", start);
    };
  }, []);

  return <canvas id="backdrop-canvas" ref={ref} aria-hidden />;
}
