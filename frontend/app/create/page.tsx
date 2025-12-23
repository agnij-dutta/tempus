"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { createPreview } from "../../lib/api";

export default function CreatePreviewPage() {
  const [ttl, setTtl] = useState(2);
  const mutation = useMutation({
    mutationFn: (hours: number) => createPreview(hours),
  });

  return (
    <main className="min-h-screen px-6 py-8">
      <h1 className="text-2xl font-semibold">Create Preview</h1>
      <p className="text-sm text-muted-foreground">
        Choose a TTL and create a new preview environment.
      </p>

      <div className="mt-6 max-w-md rounded-lg border p-4 shadow-sm bg-card">
        <label className="text-sm font-medium">TTL (hours)</label>
        <input
          type="number"
          min={1}
          max={24}
          value={ttl}
          onChange={(e) => setTtl(Number(e.target.value))}
          className="mt-2 w-full rounded-md border px-3 py-2 text-sm"
        />
        <button
          className="mt-4 w-full rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground shadow hover:opacity-90 disabled:opacity-50"
          disabled={mutation.isLoading}
          onClick={() => mutation.mutate(ttl)}
        >
          {mutation.isLoading ? "Creating..." : "Create Preview"}
        </button>

        {mutation.data && (
          <div className="mt-4 rounded-md border p-3 text-sm bg-muted">
            <div className="font-semibold">Preview created</div>
            <div>ID: {mutation.data.preview_id}</div>
            <div>URL: {mutation.data.preview_url}</div>
            <div>Expires: {new Date(mutation.data.expires_at).toLocaleString()}</div>
          </div>
        )}

        {mutation.error && (
          <div className="mt-4 text-sm text-destructive">
            Failed to create preview. {(mutation.error as any)?.message || "Unknown error"}
          </div>
        )}
      </div>
    </main>
  );
}

