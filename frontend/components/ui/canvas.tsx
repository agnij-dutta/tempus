import React, { useEffect } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

function n(this: any, e: any) {
  this.init(e || {});
}
n.prototype = {
  init: function (this: any, e: any) {
    this.phase = e.phase || 0;
    this.offset = e.offset || 0;
    this.frequency = e.frequency || 0.001;
    this.amplitude = e.amplitude || 1;
  },
  update: function (this: any) {
    return (this.phase += this.frequency), (e = this.offset + Math.sin(this.phase) * this.amplitude);
  },
  value: function (this: any) {
    return e;
  },
};

function Line(this: any, e: any) {
  this.init(e || {});
}

Line.prototype = {
  init: function (this: any, e: any) {
    this.spring = e.spring + 0.1 * Math.random() - 0.05;
    this.friction = E.friction + 0.01 * Math.random() - 0.005;
    this.nodes = [];
    for (let t, n = 0; n < E.size; n++) {
      t = new (Node as any)();
      t.x = pos.x;
      t.y = pos.y;
      this.nodes.push(t);
    }
  },
  update: function (this: any) {
    let e = this.spring,
      t = this.nodes[0];
    t.vx += (pos.x - t.x) * e;
    t.vy += (pos.y - t.y) * e;
    for (let n, i = 0, a = this.nodes.length; i < a; i++)
      (t = this.nodes[i]),
        0 < i &&
          ((n = this.nodes[i - 1]),
          (t.vx += (n.x - t.x) * e),
          (t.vy += (n.y - t.y) * e),
          (t.vx += n.vx * E.dampening),
          (t.vy += n.vy * E.dampening)),
        (t.vx *= this.friction),
        (t.vy *= this.friction),
        (t.x += t.vx),
        (t.y += t.vy),
        (e *= E.tension);
  },
  draw: function (this: any) {
    let e,
      t,
      n = this.nodes[0].x,
      i = this.nodes[0].y;
    ctx.beginPath();
    ctx.moveTo(n, i);
    for (let a = 1, o = this.nodes.length - 2; a < o; a++) {
      e = this.nodes[a];
      t = this.nodes[a + 1];
      n = 0.5 * (e.x + t.x);
      i = 0.5 * (e.y + t.y);
      ctx.quadraticCurveTo(e.x, e.y, n, i);
    }
    e = this.nodes[this.nodes.length - 2];
    t = this.nodes[this.nodes.length - 1];
    ctx.quadraticCurveTo(e.x, e.y, t.x, t.y);
    ctx.stroke();
    ctx.closePath();
  },
};

function render() {
  if (ctx.running) {
    ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    ctx.globalCompositeOperation = "lighter";
    ctx.strokeStyle = "hsla(" + Math.round(f.update()) + ",100%,50%,0.025)";
    ctx.lineWidth = 10;
    for (let t = 0; t < E.trails; t++) {
      const e = lines[t];
      e.update();
      e.draw();
    }
    ctx.frame++;
    window.requestAnimationFrame(render);
  }
}

function resizeCanvas() {
  ctx.canvas.width = window.innerWidth - 20;
  ctx.canvas.height = window.innerHeight;
}

let ctx: CanvasRenderingContext2D & { running: boolean; frame: number },
  f: any,
  e = 0,
  pos: { x: number; y: number },
  lines: any[] = [],
  E = {
    debug: true,
    friction: 0.5,
    trails: 80,
    size: 50,
    dampening: 0.025,
    tension: 0.99,
  };
function Node(this: any) {
  this.x = 0;
  this.y = 0;
  this.vy = 0;
  this.vx = 0;
}

const initLines = () => {
  lines = [];
  for (let i = 0; i < E.trails; i++) {
    lines.push(new (Line as any)({ spring: 0.45 + (i / E.trails) * 0.025 }));
  }
};

export const renderCanvas = function () {
  const canvas = document.getElementById("canvas") as HTMLCanvasElement | null;
  if (!canvas) return;
  ctx = canvas.getContext("2d") as CanvasRenderingContext2D & { running: boolean; frame: number };
  ctx.running = true;
  ctx.frame = 1;
  f = new (n as any)({
    phase: Math.random() * 2 * Math.PI,
    amplitude: 85,
    frequency: 0.0015,
    offset: 285,
  });
  const centerPos = () => {
    pos = {
      x: window.innerWidth / 2,
      y: window.innerHeight / 2,
    };
  };
  centerPos();
  initLines();
  const handleResize = () => {
    resizeCanvas();
    centerPos();
    initLines();
  };
  window.addEventListener("resize", handleResize);
  window.addEventListener("focus", () => {
    if (!ctx.running) {
      ctx.running = true;
      render();
    }
  });
  window.addEventListener("blur", () => {
    ctx.running = true;
  });
  resizeCanvas();
  render();
};

export default function CanvasHero() {
  useEffect(() => {
    renderCanvas();
  }, []);

  return (
    <section className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background">
      <div className="pointer-events-none absolute inset-0 grid-hero opacity-60" />
      <canvas id="canvas" className="absolute inset-0 h-full w-full opacity-30 dark:opacity-50" />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-background via-background/80 to-background" />
      <div className="relative z-10 mx-auto flex max-w-5xl flex-col items-center gap-6 px-6 text-center">
        <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Ephemeral previews</p>
        <h1 className="text-4xl font-semibold leading-tight md:text-5xl">
          Spin up previews that clean themselves up
        </h1>
        <p className="max-w-2xl text-lg text-muted-foreground">
          Tempus deploys on-demand environments with ALB routing, health checks, and automatic cleanup so your teams ship faster without surprise bills.
        </p>
        <div className="flex flex-wrap justify-center gap-3">
          <Link
            href="/dashboard"
            className="rounded-md bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground shadow hover:opacity-90"
          >
            Launch Dashboard
          </Link>
          <Link
            href="/create"
            className="rounded-md border px-5 py-2.5 text-sm font-medium hover:bg-muted"
          >
            Create Preview
          </Link>
        </div>
      </div>
    </section>
  );
}
