// Renders the ten CodeGuru features into #featureGrid on index.html.
// Each icon is a small hand-drawn inline SVG (no external icon library).
const CODEGURU_FEATURES = [
  { color: 'var(--amber)', title: 'Animated video explainers', desc: 'Turns a confusing concept into a short narrated, animated walkthrough.',
    icon: '<circle cx="12" cy="12" r="9"></circle><path d="M10 8.5l6 3.5-6 3.5z"></path>' },
  { color: 'var(--blue)', title: 'Plain-language explanations', desc: 'Breaks down what your code does, line by line, in everyday words.',
    icon: '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.5.4.8 1 .8 1.6h5.4c0-.6.3-1.2.8-1.6A6 6 0 0 0 12 3Z"></path>' },
  { color: 'var(--mint)', title: 'Code debugging', desc: 'Points to the exact line causing an error and suggests a fix.',
    icon: '<circle cx="12" cy="13" r="6"></circle><path d="M9 4l1.5 2M15 4l-1.5 2M4 13h2M18 13h2M6 8l1.5 1.5M18 8l-1.5 1.5"></path>' },
  { color: 'var(--amber)', title: 'Model selection', desc: 'Switch between a fast model and a deeper reasoning one mid-chat.',
    icon: '<path d="M4 6h16M4 12h16M4 18h16"></path><circle cx="8" cy="6" r="1.6" fill="currentColor" stroke="none"></circle><circle cx="16" cy="12" r="1.6" fill="currentColor" stroke="none"></circle><circle cx="10" cy="18" r="1.6" fill="currentColor" stroke="none"></circle>' },
  { color: 'var(--blue)', title: 'Dark / light mode', desc: 'A single toggle remembers your preference across visits.',
    icon: '<path d="M21 12.6A9 9 0 1 1 11.4 3a7 7 0 0 0 9.6 9.6Z"></path>' },
  { color: 'var(--mint)', title: 'Secure sign-in', desc: 'Email and password or one-tap Google login, handled by Firebase.',
    icon: '<rect x="5" y="10" width="14" height="10" rx="2"></rect><path d="M8 10V7a4 4 0 0 1 8 0v3"></path>' },
  { color: 'var(--amber)', title: 'Practice quizzes', desc: 'Generates short quizzes from whatever you just learned, on demand.',
    icon: '<rect x="4" y="3" width="16" height="18" rx="2"></rect><path d="M8 9l2.5 2.5L16 6"></path><path d="M8 16h8"></path>' },
  { color: 'var(--blue)', title: 'Auto-generated notes', desc: 'Saves a clean summary of the session for later revision.',
    icon: '<path d="M6 3h9l3 3v15H6z"></path><path d="M15 3v3h3"></path><path d="M9 12h6M9 16h6"></path>' },
  { color: 'var(--mint)', title: 'Image generation', desc: 'Creates diagrams and illustrations to go with an explanation.',
    icon: '<rect x="3" y="4" width="18" height="16" rx="2"></rect><circle cx="9" cy="10" r="1.6"></circle><path d="M3 17l5-5 4 4 3-3 6 6"></path>' },
  { color: 'var(--amber)', title: 'Chat history', desc: 'Every past conversation is saved and searchable, like a chat log.',
    icon: '<path d="M4 5h16v11H8l-4 4z"></path>' },
];

function renderFeatureGrid() {
  const grid = document.getElementById('featureGrid');
  if (!grid) return;
  grid.innerHTML = CODEGURU_FEATURES.map(f => `
    <div class="feature">
      <div class="icon-chip" style="background:color-mix(in srgb, ${f.color} 18%, transparent); color:${f.color};">
        <svg viewBox="0 0 24 24">${f.icon}</svg>
      </div>
      <div>
        <h3>${f.title}</h3>
        <p>${f.desc}</p>
      </div>
    </div>
  `).join('');
}
document.addEventListener('DOMContentLoaded', renderFeatureGrid);
