// CodeGuru dashboard controller. The UI remains local; sessions, history,
// uploads and AI responses are handled by the FastAPI backend.
(function () {
  const api = window.CodeGuruAPI;
  const chatScroll = document.getElementById('chatScroll');
  const chatInner = document.getElementById('chatInner');
  const welcomeState = document.getElementById('welcomeState');
  const input = document.getElementById('chatInput');
  const sendBtn = document.getElementById('sendBtn');
  const newChatBtn = document.getElementById('newChatBtn');
  const historyList = document.getElementById('historyList');
  const modelSelect = document.getElementById('modelSelect');
  const fileInput = document.getElementById('fileInput');
  const attachmentList = document.getElementById('attachmentList');
  const settingsPanel = document.getElementById('settingsPanel');
  const settingsBtn = document.getElementById('settingsBtn');
  const connection = JSON.parse(localStorage.getItem('codeguru-connection') || '{"mode":"local","ollamaUrl":"http://localhost:11434","provider":"groq","apiKey":""}');

  let chats = {};
  let activeChatId = null;
  let activeMessages = [];
  let uploadedFiles = [];
  let isSending = false;
  let isUploading = false;
  let activeFeature = 'chat';
  let backendGroqConfigured = false;

  function safeText(value) {
    const node = document.createElement('div');
    node.textContent = value || '';
    return node.innerHTML;
  }

  function formatMessage(text) {
    let html = safeText(text);
    const protectedParts = [];
    const protect = markup => {
      const token = 'CGPROTECTED' + protectedParts.length + 'TOKEN';
      protectedParts.push(markup);
      return token;
    };

    html = html.replace(/```(?:[a-zA-Z0-9_+-]+)?\n?([\s\S]*?)```/g, (_, code) =>
      protect('<pre>' + code.trim() + '</pre>'));
    html = html.replace(/`([^`\n]+)`/g, (_, code) => protect('<code>' + code + '</code>'));
    html = html.replace(/^#{1,3}\s+(.+)$/gm, '<strong>$1</strong>');
    html = html.replace(/^\s*[-*]\s+(.+)$/gm, '<span class="message-bullet">• $1</span>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');
    html = html.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>');
    html = html.replace(/CGPROTECTED(\d+)TOKEN/g, (_, index) => protectedParts[Number(index)]);
    return html.replace(/\n/g, '<br>');
  }

  function showStatus(message) {
    let status = document.getElementById('backendStatus');
    if (!status) {
      status = document.createElement('div');
      status.id = 'backendStatus';
      status.className = 'backend-status';
      chatInner.prepend(status);
    }
    status.textContent = message;
    status.hidden = !message;
  }

  function setBusy(busy) {
    isSending = busy;
    sendBtn.disabled = busy;
    sendBtn.setAttribute('aria-busy', String(busy));
  }

  function selectedModel() {
    return modelSelect.value || 'qwen3:8b';
  }

  function selectedProvider() {
    return connection.mode === 'api' ? 'groq' : 'ollama';
  }

  function updateConnectionUI() {
    document.getElementById('ollamaUrl').value = connection.ollamaUrl || 'http://localhost:11434';
    document.getElementById('apiKey').value = connection.apiKey || '';
    document.getElementById('localSettings').hidden = connection.mode !== 'local';
    document.getElementById('apiSettings').hidden = connection.mode !== 'api';
    document.querySelectorAll('[data-mode]').forEach(button => button.classList.toggle('active', button.dataset.mode === connection.mode));
    settingsBtn.textContent = connection.mode === 'local' ? 'LOCAL · OLLAMA ▾' : 'API MODE ▾';
  }

  async function loadModels() {
    const provider = selectedProvider();
    const data = await api.getModels(provider);
    if (provider === 'groq') backendGroqConfigured = Boolean(data.configured);
    const models = data.models || [];
    if (!models.length) throw new Error('No ' + provider + ' chat models are available from the backend.');
    const previous = modelSelect.value;
    modelSelect.replaceChildren();
    models.forEach(model => {
      const option = document.createElement('option');
      option.value = model.id;
      option.textContent = model.label + (model.installed === false ? ' · not installed' : '');
      modelSelect.appendChild(option);
    });
    if (models.some(model => model.id === previous)) modelSelect.value = previous;
  }

  function renderHistory() {
    historyList.replaceChildren();
    Object.values(chats).sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at))).forEach(chat => {
      const row = document.createElement('div');
      row.className = 'history-row';
      const button = document.createElement('button');
      button.className = 'history-item' + (chat.session_id === activeChatId ? ' active' : '');
      button.textContent = chat.title || 'New chat';
      button.title = chat.last_message || chat.title || 'New chat';
      button.addEventListener('click', () => openChat(chat.session_id));
      const remove = document.createElement('button');
      remove.className = 'delete-chat';
      remove.type = 'button';
      remove.title = 'Delete this chat';
      remove.setAttribute('aria-label', 'Delete ' + (chat.title || 'chat'));
      remove.textContent = '×';
      remove.addEventListener('click', () => deleteChat(chat.session_id));
      row.append(button, remove);
      historyList.appendChild(row);
    });
  }

  async function refreshHistory() {
    const data = await api.getChats();
    chats = Object.fromEntries((data.chats || []).map(chat => [chat.session_id, chat]));
    renderHistory();
  }

  function appendMessage(role, text, sources) {
    const row = document.createElement('div');
    row.className = 'msg-row';
    const sourceHtml = sources && sources.length
      ? '<div class="message-files">Based on uploaded files: ' + sources.map(source => safeText(source.filename)).join(', ') + '</div>'
      : '';
    row.innerHTML = '<div class="who ' + (role === 'assistant' ? 'bot' : 'user') + '">' +
      (role === 'assistant' ? 'CG' : 'You') + '</div><div class="msg-body">' + formatMessage(text) + sourceHtml + '</div>';
    chatInner.appendChild(row);
  }

  function scrollToLatest() {
    requestAnimationFrame(() => {
      chatScroll.scrollTop = chatScroll.scrollHeight;
    });
  }

  function renderMessages() {
    chatInner.querySelectorAll('.msg-row, .typing-row').forEach(node => node.remove());
    if (!activeMessages.length) {
      welcomeState.style.display = '';
      return;
    }
    welcomeState.style.display = 'none';
    activeMessages.forEach(message => appendMessage(message.role, message.content, message.sources));
    scrollToLatest();
  }

  function showTyping() {
    const row = document.createElement('div');
    row.className = 'msg-row typing-row';
    row.innerHTML = '<div class="who bot">CG</div><div class="msg-body"><div class="typing"><span></span><span></span><span></span></div></div>';
    chatInner.appendChild(row);
    scrollToLatest();
    return row;
  }

  function renderFiles() {
    attachmentList.replaceChildren();
    uploadedFiles.forEach(file => {
      const chip = document.createElement('div');
      chip.className = 'attachment-chip';
      chip.innerHTML = '<strong>⌘</strong><span>' + safeText(file.filename || file.name) + '</span>';
      attachmentList.appendChild(chip);
    });
  }

  async function createChat() {
    if (!api) return showStatus('CodeGuru API client could not load.');
    try {
      showStatus('');
      const session = await api.createChat(selectedModel(), selectedProvider());
      chats[session.session_id] = session;
      activeChatId = session.session_id;
      activeMessages = [];
      uploadedFiles = [];
      renderMessages();
      renderFiles();
      renderHistory();
      setSidebar(false);
    } catch (error) {
      showStatus(error.message);
    }
  }

  async function openChat(sessionId) {
    try {
      showStatus('');
      const [history, files] = await Promise.all([api.getChat(sessionId), api.getFiles(sessionId)]);
      activeChatId = sessionId;
      activeMessages = history.messages || [];
      uploadedFiles = files.files || [];
      if (history.session?.provider) {
        connection.mode = history.session.provider === 'groq' ? 'api' : 'local';
        updateConnectionUI();
        await loadModels();
      }
      if (history.session?.model) modelSelect.value = history.session.model;
      renderMessages();
      renderFiles();
      renderHistory();
      setSidebar(false);
    } catch (error) {
      showStatus(error.message);
    }
  }

  async function deleteChat(sessionId) {
    const chat = chats[sessionId];
    if (!confirm('Delete "' + (chat?.title || 'this chat') + '" and its uploaded files?')) return;
    try {
      await api.deleteChat(sessionId);
      delete chats[sessionId];
      if (activeChatId === sessionId) {
        activeChatId = null;
        activeMessages = [];
        uploadedFiles = [];
        const next = Object.values(chats).sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))[0];
        if (next) await openChat(next.session_id);
        else {
          renderMessages();
          renderFiles();
        }
      }
      renderHistory();
    } catch (error) {
      showStatus(error.message);
    }
  }

  async function clearHistory() {
    if (!Object.keys(chats).length || !confirm('Delete every saved CodeGuru chat and its uploaded files?')) return;
    try {
      await api.clearChats();
      chats = {};
      activeChatId = null;
      activeMessages = [];
      uploadedFiles = [];
      renderMessages();
      renderFiles();
      renderHistory();
    } catch (error) {
      showStatus(error.message);
    }
  }

  async function uploadFiles(files) {
    if (!files.length || isUploading) return;
    if (!activeChatId) await createChat();
    if (!activeChatId) return;
    isUploading = true;
    showStatus('Uploading and indexing file…');
    try {
      for (const file of Array.from(files)) {
        if (file.size > 25 * 1024 * 1024) throw new Error(file.name + ' is over the 25 MB upload limit.');
        await api.upload(activeChatId, file);
      }
      uploadedFiles = (await api.getFiles(activeChatId)).files || [];
      renderFiles();
      showStatus('');
    } catch (error) {
      showStatus(error.message);
    } finally {
      isUploading = false;
      fileInput.value = '';
    }
  }

  async function sendMessage(text, feature = activeFeature) {
    const message = text.trim();
    if (!message || isSending || isUploading) return;
    if (selectedProvider() === 'groq' && !connection.apiKey && !backendGroqConfigured) {
      showStatus('Groq needs an API key. Open API MODE and enter a key, or set GROQ_API_KEY before starting FastAPI.');
      return;
    }
    if (!activeChatId) await createChat();
    if (!activeChatId) return;

    setBusy(true);
    showStatus('');
    const localMessage = { role: 'user', content: message };
    activeMessages.push(localMessage);
    renderMessages();
    const typing = showTyping();
    try {
      const result = await api.sendMessage({
        sessionId: activeChatId,
        message,
        model: selectedModel(),
        feature,
        provider: selectedProvider(),
        apiKey: connection.mode === 'api' ? connection.apiKey : '',
      });
      activeMessages.push({ role: 'assistant', content: result.response || 'CodeGuru returned an empty response.', sources: result.rag_used ? result.sources : [] });
      typing.remove();
      renderMessages();
      await refreshHistory();
    } catch (error) {
      typing.remove();
      activeMessages.push({ role: 'assistant', content: error.message });
      renderMessages();
    } finally {
      setBusy(false);
      activeFeature = 'chat';
      document.querySelectorAll('.action-chip').forEach(chip => chip.classList.remove('active'));
    }
  }

  const sidebar = document.getElementById('sidebar');
  const sidebarBackdrop = document.createElement('button');
  sidebarBackdrop.className = 'sidebar-backdrop';
  sidebarBackdrop.setAttribute('aria-label', 'Close chat history');
  document.body.appendChild(sidebarBackdrop);
  function setSidebar(open) {
    sidebar.classList.toggle('open', open);
    sidebarBackdrop.classList.toggle('show', open);
  }

  settingsBtn.addEventListener('click', () => {
    settingsPanel.classList.toggle('open');
    document.getElementById('profilePanel')?.classList.remove('open');
  });
  document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => {
    connection.mode = button.dataset.mode;
    updateConnectionUI();
    loadModels().catch(error => showStatus(error.message));
  }));
  document.getElementById('saveSettings').addEventListener('click', () => {
    connection.ollamaUrl = document.getElementById('ollamaUrl').value.replace(/\/$/, '');
    connection.apiKey = document.getElementById('apiKey').value.trim();
    // Keep the key only in memory for this open dashboard. A deployed app
    // should use GROQ_API_KEY on the FastAPI host instead.
    localStorage.setItem('codeguru-connection', JSON.stringify({ ...connection, apiKey: '' }));
    updateConnectionUI();
    settingsPanel.classList.remove('open');
    loadModels().catch(error => showStatus(error.message));
  });
  document.getElementById('menuBtn')?.addEventListener('click', () => setSidebar(!sidebar.classList.contains('open')));
  sidebarBackdrop.addEventListener('click', () => setSidebar(false));
  newChatBtn.addEventListener('click', createChat);
  document.getElementById('clearHistoryBtn').addEventListener('click', clearHistory);
  document.getElementById('attachBtn').addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', event => uploadFiles(event.target.files));
  document.querySelector('.input-row').addEventListener('dragover', event => {
    event.preventDefault();
    event.currentTarget.classList.add('drag-active');
  });
  document.querySelector('.input-row').addEventListener('dragleave', event => event.currentTarget.classList.remove('drag-active'));
  document.querySelector('.input-row').addEventListener('drop', event => {
    event.preventDefault();
    event.currentTarget.classList.remove('drag-active');
    uploadFiles(event.dataTransfer.files);
  });
  sendBtn.addEventListener('click', event => {
    event.preventDefault();
    const text = input.value;
    input.value = '';
    input.style.height = 'auto';
    sendMessage(text);
  });
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendBtn.click();
    }
  });
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  });
  document.querySelectorAll('.action-chip').forEach(chip => chip.addEventListener('click', () => {
    activeFeature = chip.dataset.feature || 'chat';
    document.querySelectorAll('.action-chip').forEach(item => item.classList.toggle('active', item === chip));
    input.value = chip.dataset.prefix || '';
    input.focus();
  }));
  document.querySelectorAll('.quick-card').forEach(card => card.addEventListener('click', () => {
    activeFeature = card.dataset.feature || 'chat';
    sendMessage(card.dataset.prompt || '', activeFeature);
  }));
  modelSelect.addEventListener('change', () => {
    const option = modelSelect.options[modelSelect.selectedIndex];
    if (option?.textContent.includes('not installed')) {
      showStatus('Ollama model ' + selectedModel() + ' is not installed. Run: ollama pull ' + selectedModel());
    } else {
      showStatus('');
    }
    if (activeChatId && chats[activeChatId]) chats[activeChatId].model = selectedModel();
  });

  async function initialize() {
    updateConnectionUI();
    try {
      await loadModels();
      await refreshHistory();
      const newest = Object.values(chats).sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))[0];
      if (newest) await openChat(newest.session_id);
      else await createChat();
    } catch (error) {
      showStatus(error.message);
    }
  }

  initialize();
})();
