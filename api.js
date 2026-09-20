// CodeGuru FastAPI client. All dashboard/backend communication goes through
// this file so endpoint URLs and error handling stay consistent.
(function () {

  class CodeGuruApiError extends Error {
    constructor(message, status) {
      super(message);
      this.name = 'CodeGuruApiError';
      this.status = status;
    }
  }

  function messageFromPayload(payload, fallback) {
    const detail = payload && payload.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail.error === 'string') return detail.error;
    if (typeof payload?.error === 'string') return payload.error;
    return fallback;
  }

  async function backendUrl() {
    const localOverride = String(window.CodeGuruLocalBackendUrl || '').replace(/\/$/, '');
    if (localOverride) return localOverride;
    const url = String(await (window.CodeGuruRuntime || Promise.resolve(''))).replace(/\/$/, '');
    if (!url) {
      throw new CodeGuruApiError('CodeGuru backend is not configured for this deployment. Set CODEGURU_API_URL in Vercel.', 0);
    }
    return url;
  }

  async function request(path, options = {}, timeoutMs = 120000) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch((await backendUrl()) + path, { ...options, signal: controller.signal });
      const contentType = response.headers.get('content-type') || '';
      const payload = contentType.includes('application/json') ? await response.json() : null;
      if (!response.ok) throw new CodeGuruApiError(messageFromPayload(payload, 'CodeGuru backend request failed.'), response.status);
      return payload;
    } catch (error) {
      if (error.name === 'AbortError') throw new CodeGuruApiError('CodeGuru took too long to respond. Please try again.', 408);
      if (error instanceof CodeGuruApiError) throw error;
      throw new CodeGuruApiError('CodeGuru backend is not running or cannot be reached.', 0);
    } finally {
      clearTimeout(timeout);
    }
  }

  window.CodeGuruAPI = {
    getModels: provider => request('/api/models?provider=' + encodeURIComponent(provider || 'ollama'), {}, 10000),
    createChat: (model, provider) => request('/api/chat/new', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model, provider }),
    }),
    getChats: () => request('/api/chats', {}, 15000),
    getChat: sessionId => request('/api/chats/' + encodeURIComponent(sessionId), {}, 15000),
    deleteChat: sessionId => request('/api/chats/' + encodeURIComponent(sessionId), { method: 'DELETE' }),
    clearChats: () => request('/api/chats', { method: 'DELETE' }),
    getFiles: sessionId => request('/api/files/' + encodeURIComponent(sessionId), {}, 30000),
    upload: (sessionId, file) => {
      const data = new FormData();
      data.append('file', file);
      return request('/api/upload/' + encodeURIComponent(sessionId), { method: 'POST', body: data }, 180000);
    },
    sendMessage: ({ sessionId, message, model, feature, provider, apiKey }) => request('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        message,
        model,
        feature,
        provider,
        api_key: apiKey || undefined,
      }),
    }, 180000),
  };
})();
