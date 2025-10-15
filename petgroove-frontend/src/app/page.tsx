'use client';

import { useCallback, useMemo, useRef, useState } from 'react';

type JobStatus = 'idle' | 'queued' | 'processing' | 'done' | 'error';

type CreateJobBody = {
  image_url: string;
  motion_id: string;
  style: string;
};

type CreateJobResponse = {
  id: string;
  status: JobStatus;
  video_url?: string | null;
  error?: string | null;
};

type GetJobResponse = {
  id: string;
  status: JobStatus;
  video_url?: string | null;
  error?: string | null;
};

type UploadResponse = {
  url: string;
};

const MOTIONS = [
  { id: 'tiktok_hiphop_01', label: 'TikTok Hiphop 01' },
  // add more here later
];

const STYLES = [
  { id: 'photoreal', label: 'photoreal' },
  // add more here later
];

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000';
const POLL_MS = Number(process.env.NEXT_PUBLIC_POLL_INTERVAL_MS ?? 1200);

function isHttpUrl(s: string): boolean {
  try {
    const u = new URL(s);
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
}

export default function Page() {
  const [imageUrl, setImageUrl] = useState<string>('');
  const [motionId, setMotionId] = useState<string>(MOTIONS[0].id);
  const [style, setStyle] = useState<string>(STYLES[0].id);

  const [status, setStatus] = useState<JobStatus>('idle');
  const [jobId, setJobId] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [uploadName, setUploadName] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const canSubmit = useMemo(() => {
    return isHttpUrl(imageUrl) && motionId.length > 0 && style.length > 0 && status !== 'processing';
  }, [imageUrl, motionId, style, status]);

  const startPoll = useCallback(async (id: string) => {
    let keepGoing = true;

    while (keepGoing) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      try {
        const r = await fetch(`${API_BASE}/jobs/${id}`);
        if (!r.ok) {
          throw new Error(`poll failed: ${r.status}`);
        }
        const data = (await r.json()) as GetJobResponse;
        setStatus(data.status);
        if (data.status === 'done') {
          setVideoUrl(data.video_url ?? null);
          setError(null);
          keepGoing = false;
        } else if (data.status === 'error') {
          setVideoUrl(null);
          setError(data.error ?? 'Unknown error');
          keepGoing = false;
        }
      } catch (e) {
        setError((e as Error).message);
        keepGoing = false;
      }
    }
  }, []);

  const submit = useCallback(async () => {
    if (!isHttpUrl(imageUrl)) {
      setError('Please provide a valid image URL or upload a file.');
      return;
    }
    setStatus('queued');
    setVideoUrl(null);
    setError(null);

    try {
      const body: CreateJobBody = {
        image_url: imageUrl,
        motion_id: motionId,
        style,
      };
      const r = await fetch(`${API_BASE}/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const text = await r.text();
        throw new Error(`create failed: ${r.status} ${text}`);
      }
      const data = (await r.json()) as CreateJobResponse;
      setJobId(data.id);
      setStatus(data.status);
      startPoll(data.id);
    } catch (e) {
      setStatus('error');
      setError((e as Error).message);
    }
  }, [API_BASE, imageUrl, motionId, style, startPoll]);

  const upload = useCallback(async (file: File) => {
    setIsUploading(true);
    setUploadName(file.name);
    setError(null);

    try {
      const fd = new FormData();
      fd.append('file', file);
      const r = await fetch(`${API_BASE}/upload`, {
        method: 'POST',
        body: fd,
      });
      if (!r.ok) {
        const text = await r.text();
        throw new Error(`upload failed: ${r.status} ${text}`);
      }
      const data = (await r.json()) as UploadResponse;
      setImageUrl(data.url); // switch the form into URL mode with the public URL
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setIsUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }, []);

  const onFileChanged = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0];
      if (f) {
        void upload(f);
      }
    },
    [upload]
  );

  return (
    <main className="min-h-dvh bg-neutral-950 text-neutral-100">
      <div className="mx-auto max-w-5xl px-4 py-10">
        <h1 className="text-3xl font-semibold tracking-tight">PetGroove</h1>
        <p className="mt-2 text-neutral-300">
          Turn a pet photo into a short video with one click.
        </p>

        {/* Card */}
        <div className="mt-8 rounded-xl border border-neutral-800 bg-neutral-900/60 p-5 shadow-lg">
          {/* URL input */}
          <label className="block text-sm font-medium text-neutral-300">Image URL</label>
          <input
            className="mt-1 w-full rounded-md border border-neutral-700 bg-neutral-800 px-3 py-2 text-neutral-100 outline-none focus:ring-2 focus:ring-indigo-500"
            placeholder="https://example.com/cat.jpg"
            value={imageUrl}
            onChange={(e) => setImageUrl(e.target.value)}
          />

          {/* Uploader */}
          <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
            <div>
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                onChange={onFileChanged}
                className="block w-full text-sm file:mr-4 file:cursor-pointer file:rounded-md file:border-0 file:bg-neutral-800 file:px-4 file:py-2 file:text-sm file:text-neutral-100 hover:file:bg-neutral-700"
              />
            </div>
            <div className="text-xs text-neutral-400">
              {isUploading ? `Uploading ${uploadName ?? 'image'}…` : 'Or upload a file (auto-uploads)'}
            </div>
          </div>

          {/* Controls */}
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-neutral-300">Motion preset</label>
              <select
                value={motionId}
                onChange={(e) => setMotionId(e.target.value)}
                className="mt-1 w-full rounded-md border border-neutral-700 bg-neutral-800 px-3 py-2 text-neutral-100 outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {MOTIONS.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-300">Style</label>
              <select
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                className="mt-1 w-full rounded-md border border-neutral-700 bg-neutral-800 px-3 py-2 text-neutral-100 outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {STYLES.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="mt-6">
            <button
              onClick={submit}
              disabled={!canSubmit}
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Generate video
            </button>
          </div>
        </div>

        {/* Status */}
        <div className="mt-4 text-sm">
          <span className="text-neutral-400">Status:</span>{' '}
          <span className={status === 'error' ? 'text-red-400' : 'text-neutral-200'}>
            {status} {jobId ? `(${jobId})` : ''}
          </span>
        </div>
        {error && (
          <div className="mt-3 rounded-md border border-red-800 bg-red-950/60 p-3 text-sm text-red-300">
            {error}
          </div>
        )}

        {/* Panels */}
        <div className="mt-6 grid gap-6 sm:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-medium text-neutral-300">Input image preview</h3>
            <div className="aspect-[4/3] w-full overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900">
              {imageUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={imageUrl}
                  alt="preview"
                  className="h-full w-full object-cover"
                />
              ) : (
                <div className="flex h-full items-center justify-center text-neutral-500">
                  No image yet
                </div>
              )}
            </div>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-medium text-neutral-300">Result</h3>
            <div className="aspect-[4/3] w-full overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900">
              {videoUrl ? (
                <video
                  controls
                  playsInline
                  className="h-full w-full"
                  src={videoUrl}
                />
              ) : (
                <div className="flex h-full items-center justify-center text-neutral-500">
                  No result yet
                </div>
              )}
            </div>
          </div>
        </div>

        <p className="mt-8 text-center text-xs text-neutral-500">
          API: {API_BASE}
        </p>
      </div>
    </main>
  );
}