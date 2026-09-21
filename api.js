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
      if (!response.ok) {
        const fallback = response.status === 413
          ? 'That file is too large for the server. On the hosted site, files must be about 4 MB or smaller.'
          : 'CodeGuru backend request failed.';
        throw new CodeGuruApiError(messageFromPayload(payload, fallback), response.status);
      }
      return payload;
    } catch (error) {
      if (error.name === 'AbortError') throw new CodeGuruApiError('CodeGuru took too long to respond. Please try again.', 408);
      if (error instanceof CodeGuruApiError) throw error;
      throw new CodeGuruApiError('CodeGuru backend is not running or cannot be reached.', 0);
    } finally {
      clearTimeout(timeout);
    }
  }

  async function streamChat(payload, onToken) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 180000);
    try {
      const response = await fetch((await backendUrl()) + '/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new CodeGuruApiError(messageFromPayload(error, 'Local Ollama is offline.'), response.status);
      }
      const reader = response.body?.getReader();
      if (!reader) throw new CodeGuruApiError('Streaming is not supported by this browser.', 0);
      const decoder = new TextDecoder();
      let responseText = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const token = decoder.decode(value, { stream: true });
        responseText += token;
        onToken(token, responseText);
      }
      responseText += decoder.decode();
      return { response: responseText };
    } catch (error) {
      if (error.name === 'AbortError') throw new CodeGuruApiError('Local Ollama took too long to respond. Please choose another configured model.', 503);
      if (error instanceof CodeGuruApiError) throw error;
      throw new CodeGuruApiError('Local Ollama is offline. Choose another configured model and try again.', 503);
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
    upload: (sessionId, file, provider) => {
      const data = new FormData();
      data.append('file', file);
      if (provider) data.append('provider', provider);
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
    streamOllamaMessage: ({ sessionId, message, model, feature }, onToken) => streamChat({
      session_id: sessionId, message, model, feature, provider: 'ollama',
    }, onToken),
  };
})();
