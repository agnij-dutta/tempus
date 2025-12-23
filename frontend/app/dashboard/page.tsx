"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { listPreviews } from "@/lib/api";
import { Home, Plus, RefreshCw, Table } from "lucide-react";

export default function DashboardPage() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["previews"],
    queryFn: listPreviews,
    refetchInterval: 15000,
  });

  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="flex min-h-screen">
        <aside className="hidden w-64 flex-shrink-0 flex-col border-r bg-card/60 p-4 backdrop-blur md:flex">
          <div className="text-lg font-semibold">Tempus</div>
          <p className="text-xs text-muted-foreground">Preview Control</p>
          <div className="mt-6 space-y-2 text-sm">
            <NavLink href="/" icon={<Home className="h-4 w-4" />}>
              Landing
            </NavLink>
            <NavLink href="/dashboard" icon={<Table className="h-4 w-4" />}>
              Dashboard
            </NavLink>
            <NavLink href="/create" icon={<Plus className="h-4 w-4" />}>
              Create Preview
            </NavLink>
          </div>
          <div className="mt-auto">
            <button
              onClick={() => refetch()}
              className="flex w-full items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-muted"
            >
              <RefreshCw className="h-4 w-4" />
              Refresh
            </button>
          </div>
        </aside>

        <div className="flex-1 px-6 py-8">
          <header className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-semibold">Dashboard</h1>
              <p className="text-sm text-muted-foreground">
                Manage and test your preview environments
              </p>
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => refetch()}
                className="rounded-md border px-3 py-2 text-sm hover:bg-muted"
              >
                Refresh
              </button>
              <Link
                href="/create"
                className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground shadow hover:opacity-90"
              >
                Create Preview
              </Link>
            </div>
          </header>

          <section className="mt-8">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">Active Previews</h2>
              <span className="text-xs text-muted-foreground">
                Auto-refreshing every 15s
              </span>
            </div>
            {isLoading && <div className="mt-4 text-sm text-muted-foreground">Loading previews…</div>}
            {error && (
              <div className="mt-4 text-sm text-destructive">
                Failed to load previews. Check API URL.
              </div>
            )}
            <div className="mt-4 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {data?.items.map((item) => (
                <div key={item.preview_id} className="rounded-lg border p-4 shadow-sm bg-card">
                  <div className="flex items-center justify-between">
                    <span className="text-xs uppercase tracking-wide text-muted-foreground">
                      {item.status}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      Expires: {new Date(item.expires_at).toLocaleString()}
                    </span>
                  </div>
                  <h3 className="mt-2 text-base font-semibold break-all">
                    {item.preview_id}
                  </h3>
                  <p className="text-sm text-muted-foreground truncate">
                    {item.preview_url}
                  </p>
                  <div className="mt-4 flex gap-2">
                    <Link
                      href={`/preview/${item.preview_id}`}
                      className="text-sm text-primary underline"
                    >
                      Details
                    </Link>
                    <a
                      href={item.preview_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sm text-primary underline"
                    >
                      Open
                    </a>
                  </div>
                </div>
              ))}
            </div>
            {!isLoading && data?.items.length === 0 && (
              <div className="mt-4 text-sm text-muted-foreground">No previews yet.</div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}

function NavLink({
  href,
  icon,
  children,
}: {
  href: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className="flex items-center gap-2 rounded-md px-2 py-2 text-sm hover:bg-muted"
    >
      {icon}
      <span>{children}</span>
    </Link>
  );
}

