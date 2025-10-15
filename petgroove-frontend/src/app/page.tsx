'use client';

import * as React from 'react';
import { useState, useEffect } from 'react';

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, '') ?? 'https://api.petgroove.app';

type JobStatus = 'queued' | 'processing' | 'done' | 'error';

interface JobResponse {
  id: string;
  status: JobStatus;
  video_url?: string | null;
  error?: string | null;
}

export default function Page() {
  const [imageUrl, setImageUrl] = useState(
    'https://picul.de/700x500/pm/Yhv'
  );
  const [motionId, setMotionId] = useState('tiktok_hiphop_01');
  const [style, setStyle] = useState('photoreal');
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<JobStatus | 'idle'>('idle');
  const [error, setError] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);

  // Submit handler
  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    setVideoUrl(null);
    setStatus('queued');

    try {
      const res = await fetch(`${API_BASE}/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_url: imageUrl, motion_id: motionId, style }),
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `POST /jobs failed (${res.status})`);
      }

      const data: JobResponse = await res.json();
      setJobId(data.id);
      setStatus('queued');
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  // Polling
  useEffect(() => {
    if (!jobId) return;

    let stop = false;
    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/jobs/${jobId}`);
        if (!res.ok) throw new Error(`GET /jobs/${jobId} failed (${res.status})`);
        const data: JobResponse = await res.json();

        if (stop) return;

        setStatus(data.status);
        if (data.status === 'done') {
          setVideoUrl(data.video_url ?? null);
        }
        if (data.status === 'error') {
          setError(data.error ?? 'Unknown error');
        }
        if (data.status === 'queued' || data.status === 'processing') {
          setTimeout(poll, Number(process.env.NEXT_PUBLIC_POLL_INTERVAL_MS ?? 1200));
        }
      } catch (err) {
        if (!stop) {
          setStatus('error');
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    };

    poll();
    return () => {
      stop = true;
    };
  }, [jobId]);

  // Typed change handlers (remove `any`)
  const onChangeImage = (e: React.ChangeEvent<HTMLInputElement>) =>
    setImageUrl(e.target.value);

  const onChangeMotion = (e: React.ChangeEvent<HTMLSelectElement>) =>
    setMotionId(e.target.value);

  const onChangeStyle = (e: React.ChangeEvent<HTMLInputElement>) =>
    setStyle(e.target.value);

  return (
    <main className="min-h-screen bg-black text-white">
      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <h1 className="text-3xl font-bold">PetGroove</h1>
        <p className="text-zinc-400">Turn a pet photo into a short video with one click.</p>

        <form onSubmit={onSubmit} className="space-y-4 rounded-lg border border-zinc-800 p-4">
          <label className="block text-sm text-zinc-400">Image URL</label>
          <input
            className="w-full rounded-md bg-zinc-900 border border-zinc-800 p-3"
            type="url"
            value={imageUrl}
            onChange={onChangeImage}
            placeholder="https://…"
            required
          />

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-zinc-400">Motion preset</label>
              <select
                className="w-full rounded-md bg-zinc-900 border border-zinc-800 p-3"
                value={motionId}
                onChange={onChangeMotion}
              >
                <option value="tiktok_hiphop_01">TikTok Hiphop 01</option>
                <option value="tiktok_hiphop_02">TikTok Hiphop 02</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-zinc-400">Style</label>
              <input
                className="w-full rounded-md bg-zinc-900 border border-zinc-800 p-3"
                value={style}
                onChange={onChangeStyle}
                placeholder="photoreal"
              />
            </div>
          </div>

          <button
            type="submit"
            className="rounded-md bg-violet-600 hover:bg-violet-500 px-4 py-2 font-medium"
          >
            Generate video
          </button>
        </form>

        <div className="text-sm">
          <div className="text-zinc-400">
            Status: <span className="text-white">{status}</span>
            {error ? (
              <div className="mt-2 rounded-md bg-red-900/40 border border-red-800 p-3 text-red-200">
                {error}
              </div>
            ) : null}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <h3 className="mb-2 text-zinc-400 text-sm">Input image preview</h3>
            <div className="aspect-video rounded-md border border-zinc-800 overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={imageUrl} alt="" className="w-full h-full object-cover" />
            </div>
          </div>

          <div>
            <h3 className="mb-2 text-zinc-400 text-sm">Result</h3>
            <div className="aspect-video rounded-md border border-zinc-800 overflow-hidden flex items-center justify-center">
              {videoUrl ? (
                <video src={videoUrl} controls className="w-full h-full" />
              ) : (
                <span className="text-zinc-600">No result yet</span>
              )}
            </div>
          </div>
        </div>

        <p className="text-xs text-zinc-500">
          API: {API_BASE}
        </p>
      </div>
    </main>
  );
}