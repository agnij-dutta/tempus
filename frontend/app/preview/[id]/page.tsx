"use client";

import { useParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { deletePreview, extendPreview, getPreview, testPreview } from "../../../lib/api";

export default function PreviewDetailsPage() {
  const params = useParams<{ id: string }>();
  const previewId = params?.id;

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["preview", previewId],
    queryFn: () => getPreview(previewId),
    enabled: !!previewId,
    refetchInterval: 15000,
  });

  const extendMutation = useMutation({
    mutationFn: (hours: number) => extendPreview(previewId, hours),
    onSuccess: () => refetch(),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deletePreview(previewId),
    onSuccess: () => refetch(),
  });

  const testMutation = useMutation({
    mutationFn: () => testPreview(previewId),
  });

  if (!previewId) {
    return <div className="p-6 text-sm text-destructive">No preview ID provided.</div>;
  }

  return (
    <main className="min-h-screen px-6 py-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Preview {previewId}</h1>
          <p className="text-sm text-muted-foreground">Details and actions</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => refetch()}
            className="rounded-md border px-3 py-2 text-sm hover:bg-muted"
          >
            Refresh
          </button>
          <button
            onClick={() => deleteMutation.mutate()}
            className="rounded-md border px-3 py-2 text-sm text-destructive hover:bg-muted"
            disabled={deleteMutation.isPending}
          >
            {deleteMutation.isPending ? "Deleting..." : "Delete"}
          </button>
        </div>
      </div>

      {isLoading && <div className="mt-4 text-sm text-muted-foreground">Loading...</div>}
      {error && (
        <div className="mt-4 text-sm text-destructive">
          Failed to load preview. {(error as any)?.message || "Unknown error"}
        </div>
      )}

      {data && (
        <section className="mt-6 grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border p-4 shadow-sm bg-card">
            <div className="text-xs uppercase text-muted-foreground">Status</div>
            <div className="mt-1 text-lg font-semibold">{data.status}</div>
            <div className="mt-3 text-sm text-muted-foreground">
              Expires: {new Date(data.expires_at).toLocaleString()}
            </div>
            <div className="text-sm text-muted-foreground">
              Created: {new Date(data.created_at).toLocaleString()}
            </div>
            <div className="mt-3 text-sm">
              <div className="font-semibold">Service</div>
              <div>Status: {data.service_status || "unknown"}</div>
              <div>Desired: {data.desired_count ?? "-"}</div>
              <div>Running: {data.running_count ?? "-"}</div>
            </div>
            <div className="mt-3 text-sm">
              <div className="font-semibold">Target Group</div>
              <div>Health: {data.target_group_health || "unknown"}</div>
            </div>
          </div>

          <div className="rounded-lg border p-4 shadow-sm bg-card space-y-3">
            <div>
              <div className="text-xs uppercase text-muted-foreground">Preview URL</div>
              <a href={data.preview_url} target="_blank" rel="noreferrer" className="text-sm text-primary underline break-all">
                {data.preview_url}
              </a>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => extendMutation.mutate(1)}
                className="rounded-md border px-3 py-2 text-sm hover:bg-muted"
                disabled={extendMutation.isPending}
              >
                {extendMutation.isPending ? "Extending..." : "Extend +1h"}
              </button>
              <button
                onClick={() => testMutation.mutate()}
                className="rounded-md border px-3 py-2 text-sm hover:bg-muted"
                disabled={testMutation.isPending}
              >
                {testMutation.isPending ? "Testing..." : "Test URL"}
              </button>
            </div>

            {extendMutation.data && (
              <div className="rounded-md border p-3 text-sm bg-muted">
                New expiry: {extendMutation.data.expires_at}
              </div>
            )}
            {testMutation.data && (
              <div className="rounded-md border p-3 text-sm bg-muted space-y-1">
                <div className="font-semibold">Test Result</div>
                <div>Status: {testMutation.data.result?.status_code ?? "error"}</div>
                {testMutation.data.result?.error && (
                  <div className="text-destructive">{testMutation.data.result.error}</div>
                )}
              </div>
            )}
          </div>
        </section>
      )}
    </main>
  );
}

