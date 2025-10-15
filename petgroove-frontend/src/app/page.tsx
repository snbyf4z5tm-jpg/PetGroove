'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

type CreateJobResponse = {
  id: string;
  status: 'queued' | 'processing' | 'done' | 'error';
  video_url?: string | null;
  error?: string | null;
};

type GetJobResponse = CreateJobResponse;

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/+$/, '') || 'http://localhost:8000';

const MOTIONS = [
  { id: 'tiktok_hiphop_01', label: 'TikTok Hiphop 01' },
  // add more when you have them
];

export default function HomePage() {
  const [imageUrl, setImageUrl] = useState(
    'https://upload.wikimedia.org/wikipedia/commons/3/3a/Cat03.jpg'
  );
  const [motionId, setMotionId] = useState(MOTIONS[0].id);
  const [style, setStyle] = useState('photoreal');

  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<'idle' | 'queued' | 'processing' | 'done' | 'error'>('idle');
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  async function createJob(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setVideoUrl(null);
    setJobId(null);
    setStatus('queued');

    try {
      const res = await fetch(`${API_BASE}/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_url: imageUrl,
          motion_id: motionId,
          style: style || 'photoreal',
        }),
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Create failed: ${res.status} ${text}`);
      }

      const data: CreateJobResponse = await res.json();
      setJobId(data.id);
      setStatus(data.status);

      // Start polling
      startPolling(data.id);
    } catch (err: any) {
      setStatus('error');
      setError(err.message || String(err));
    }
  }

  function startPolling(id: string) {
    if (pollingRef.current) clearInterval(pollingRef.current);

    pollingRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/jobs/${id}`);
        if (!res.ok) throw new Error(`Poll failed: ${res.status}`);
        const data: GetJobResponse = await res.json();

        setStatus(data.status);
        if (data.status === 'done') {
          setVideoUrl(data.video_url || null);
          clearIntervalIfAny();
        } else if (data.status === 'error') {
          setError(data.error || 'Unknown error');
          clearIntervalIfAny();
        }
      } catch (err: any) {
        setStatus('error');
        setError(err.message || String(err));
        clearIntervalIfAny();
      }
    }, 2000);
  }

  function clearIntervalIfAny() {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }

  const isWorking = status === 'queued' || status === 'processing';

  return (
    <main className="min-h-dvh bg-neutral-950 text-neutral-100">
      <div className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-3xl font-semibold tracking-tight">PetGroove</h1>
        <p className="text-neutral-400 mt-2">
          Turn a pet photo into a short video with one click.
        </p>

        <form onSubmit={createJob} className="mt-8 space-y-6 rounded-xl border border-neutral-800 p-6">
          <div className="space-y-2">
            <label className="block text-sm font-medium text-neutral-300">Image URL</label>
            <input
              className="w-full rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500"
              value={imageUrl}
              onChange={(e) => setImageUrl(e.target.value)}
              placeholder="https://example.com/pet.jpg"
              required
            />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <label className="block text-sm font-medium text-neutral-300">Motion preset</label>
              <select
                className="w-full rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500"
                value={motionId}
                onChange={(e) => setMotionId(e.target.value)}
              >
                {MOTIONS.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-2">
              <label className="block text-sm font-medium text-neutral-300">Style</label>
              <input
                className="w-full rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500"
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                placeholder="photoreal"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={isWorking}
            className="inline-flex items-center rounded-md bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {isWorking ? 'Generating…' : 'Generate video'}
          </button>
        </form>

        {/* Status / errors */}
        <div className="mt-6">
          {status !== 'idle' && (
            <div className="text-sm text-neutral-300">
              <span className="font-medium">Status:</span> {status}
              {jobId && <span className="ml-2 text-neutral-500">({jobId})</span>}
            </div>
          )}
          {error && <div className="mt-2 rounded-md bg-red-950/40 p-3 text-red-300">{error}</div>}
        </div>

        {/* Preview */}
        <div className="mt-10 grid gap-6 sm:grid-cols-2">
          <div>
            <div className="text-sm text-neutral-400 mb-2">Input image preview</div>
            <div className="aspect-square overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={imageUrl} alt="input" className="h-full w-full object-cover" />
            </div>
          </div>

          <div>
            <div className="text-sm text-neutral-400 mb-2">Result</div>
            <div className="aspect-square overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900 flex items-center justify-center">
              {videoUrl ? (
                <video className="h-full w-full object-cover" src={videoUrl} controls />
              ) : (
                <span className="text-neutral-500">No result yet</span>
              )}
            </div>
          </div>
        </div>

        <footer className="mt-12 text-center text-xs text-neutral-500">
          API: <code>{API_BASE}</code>
        </footer>
      </div>
    </main>
  );
}