"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import CanvasHero from "@/components/ui/canvas";
import DatabaseWithRestApi from "@/components/ui/database-with-rest-api";
import { LetsWorkTogether } from "@/components/ui/lets-work-section";
import { Testimonial } from "@/components/ui/design-testimonial";
import { TextShimmer } from "@/components/ui/text-shimmer";
import { Footer7 } from "@/components/ui/footer-7";
import { ThemeToggle } from "@/components/theme-toggle";

export default function LandingPage() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="absolute right-4 top-4 z-50">
        <ThemeToggle />
      </div>
      <CanvasHero />

      <section className="mx-auto flex max-w-6xl flex-col gap-12 px-6 py-16 md:px-10">
        <div className="grid gap-10 lg:grid-cols-[1.2fr_0.8fr] items-center">
          <div className="space-y-4">
            <TextShimmer className="text-sm uppercase tracking-[0.3em] text-muted-foreground">
              Ship safer, faster
            </TextShimmer>
            <h2 className="text-3xl font-semibold leading-tight md:text-4xl">
              From PR to live preview in seconds.
            </h2>
            <p className="text-lg text-muted-foreground">
              Create disposable environments per branch with a stable URL, health checks,
              and automatic teardown. Tempus wires up ECS, ALB, DynamoDB, and EventBridge so
              you can focus on the product.
            </p>
            <div className="flex gap-3">
              <Link
                href="/dashboard"
                className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground shadow hover:opacity-90"
              >
                Go to dashboard <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="/create"
                className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-sm hover:bg-muted"
              >
                Create preview
              </Link>
            </div>
          </div>
          <div className="flex justify-center">
            <DatabaseWithRestApi
              title="Observability-ready"
              badgeTexts={{
                first: "Health checks",
                second: "Logs wired",
                third: "Auto-cleanup",
                fourth: "Cost-aware",
              }}
              buttonTexts={{
                first: "Launch",
                second: "Monitor",
              }}
              circleText="Tempus • Previews • Tempus • Previews"
            />
          </div>
        </div>

        <div className="grid gap-8 lg:grid-cols-2">
          <div className="rounded-2xl border bg-card p-6 shadow-sm">
            <div className="flex items-center gap-2 text-sm font-semibold text-primary">
              <TextShimmer className="text-xs uppercase tracking-[0.3em]">
                Teams love speed
              </TextShimmer>
            </div>
            <Testimonial />
          </div>
          <div className="rounded-2xl border bg-card p-6 shadow-sm">
            <h3 className="text-xl font-semibold">Works across your stack</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Bring any containerized service. Tempus deploys to ECS Fargate, fronts with ALB,
              schedules cleanup via EventBridge, and tracks metadata in DynamoDB.
            </p>
            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              <FeatureCard title="One-click previews" desc="TTL-based, cost-safe environments." />
              <FeatureCard title="Routing-ready" desc="Per-preview ALB routes with health checks." />
              <FeatureCard title="Observability" desc="Logs in CloudWatch, health + status APIs." />
              <FeatureCard title="Safe cleanup" desc="Lambda cleanup on schedule or manual delete." />
            </div>
          </div>
        </div>
      </section>

      <section className="border-t bg-muted/30 py-14">
        <div className="mx-auto max-w-6xl px-6 md:px-10">
          <LetsWorkTogether />
        </div>
      </section>
      <Footer7 />
    </main>
  );
}

function FeatureCard({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="rounded-xl border bg-background p-4 shadow-sm">
      <div className="text-sm font-semibold">{title}</div>
      <p className="mt-1 text-sm text-muted-foreground">{desc}</p>
    </div>
  );
}

