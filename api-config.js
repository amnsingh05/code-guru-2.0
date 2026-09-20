// CodeGuru backend URL resolver.
// Local development talks directly to FastAPI. On Vercel, the URL is supplied
// at runtime by /api/runtime-config from the CODEGURU_API_URL environment variable.
(function () {
  const isLocalHost = ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
  const localUrl = 'http://localhost:8000';

  window.CodeGuruRuntime = (async () => {
    if (window.CODEGURU_API_URL) return window.CODEGURU_API_URL;
    if (isLocalHost) return localUrl;
    try {
      const response = await fetch('/api/runtime-config', { cache: 'no-store' });
      if (!response.ok) return '';
      const config = await response.json();
      return config.apiUrl || '';
    } catch {
      return '';
    }
  })();
})();
