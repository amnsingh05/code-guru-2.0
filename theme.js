// Shared dark/light mode toggle. Persists choice in localStorage,
// falls back to the OS preference on first visit.
(function () {
  const root = document.documentElement;
  const stored = localStorage.getItem('codeguru-theme');
  const prefersLight = window.matchMedia('(prefers-color-scheme: light)').matches;
  const initial = stored || (prefersLight ? 'light' : 'dark');
  root.setAttribute('data-theme', initial);

  function paintIcon(theme) {
    const icon = document.getElementById('themeIcon');
    if (!icon) return;
    icon.innerHTML = theme === 'light'
      ? '<path d="M21 12.6A9 9 0 1 1 11.4 3a7 7 0 0 0 9.6 9.6Z"></path>'
      : '<circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path>';
  }
  paintIcon(initial);

  const btn = document.getElementById('themeToggle');
  if (btn) {
    btn.addEventListener('click', () => {
      const next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      root.setAttribute('data-theme', next);
      localStorage.setItem('codeguru-theme', next);
      paintIcon(next);
    });
  }
})();

// Subtle scroll reveals for the marketing page. This stays inactive elsewhere.
document.addEventListener('DOMContentLoaded', () => {
  const targets = document.querySelectorAll('#features, #workflow, .cta');
  if (!targets.length) return;
  if (!('IntersectionObserver' in window)) {
    targets.forEach(el => el.classList.add('is-visible'));
    return;
  }
  targets.forEach(el => el.classList.add('reveal'));
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  targets.forEach(el => observer.observe(el));
});
