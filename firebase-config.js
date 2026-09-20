// Firebase web configuration for CodeGuru.
//
// This project is served directly by FastAPI, not bundled by Vite. Therefore
// import.meta.env is unavailable in the browser. The deployed FastAPI function
// reads Vercel environment variables and exposes this *public Firebase web
// configuration only at runtime.
const response = await fetch('/api/firebase-config', { cache: 'no-store' });

if (!response.ok) {
  let detail = 'Firebase configuration could not be loaded.';
  try {
    const payload = await response.json();
    detail = payload.detail || detail;
  } catch {
    // Keep the useful fallback message when a proxy returns non-JSON content.
  }
  throw new Error(detail);
}

export const firebaseConfig = await response.json();
