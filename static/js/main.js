// AOneArt – Main JS

// Navbar scroll
window.addEventListener('scroll', () => {
  document.getElementById('navbar')?.classList.toggle('scrolled', window.scrollY > 40);
});

// Mobile nav
function toggleNav() {
  document.getElementById('navLinks')?.classList.toggle('open');
}
document.addEventListener('click', e => {
  const links = document.getElementById('navLinks');
  const burger = document.getElementById('hamburger');
  if (links?.classList.contains('open') && !links.contains(e.target) && !burger?.contains(e.target)) {
    links.classList.remove('open');
  }
});

// Cart count
async function updateCartCount() {
  try {
    const res = await fetch('/cart_count');
    const data = await res.json();
    const badge = document.getElementById('cartCount');
    if (badge) {
      badge.textContent = data.count;
      badge.style.display = data.count > 0 ? 'flex' : 'none';
    }
  } catch (e) {}
}

// Qty control
function changeQty(delta) {
  const inp = document.getElementById('qtyInput');
  if (!inp) return;
  let v = Math.max(1, Math.min(99, parseInt(inp.value || 1) + delta));
  inp.value = v;
}

// Payment method info
function setupPayment() {
  document.querySelectorAll('.pay-radio').forEach(r => {
    r.addEventListener('change', () => {
      document.querySelectorAll('.pay-info').forEach(el => el.classList.remove('show'));
      document.getElementById('pi_' + r.value)?.classList.add('show');
    });
  });
}

// FAQ accordion
function setupFAQ() {
  document.querySelectorAll('.faq-q').forEach(q => {
    q.addEventListener('click', () => {
      const item = q.parentElement;
      const isOpen = item.classList.contains('open');
      document.querySelectorAll('.faq-item').forEach(i => i.classList.remove('open'));
      if (!isOpen) item.classList.add('open');
    });
  });
}

// Stars rating picker
function setupStars() {
  const picker = document.querySelector('.stars-picker');
  if (!picker) return;
  const labels = [...picker.querySelectorAll('label')].reverse();
  labels.forEach((lbl, i) => {
    lbl.addEventListener('mouseenter', () => {
      labels.forEach((l, j) => l.style.color = j <= i ? 'var(--gold)' : 'var(--dark4)');
    });
    lbl.addEventListener('mouseleave', () => {
      labels.forEach(l => l.style.color = '');
    });
  });
}

// Scroll reveal
function setupReveal() {
  const els = document.querySelectorAll('.product-card, .feature-item, .testi-card, .about-card, .faq-item');
  const obs = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add('revealed'); obs.unobserve(e.target); }
    });
  }, { threshold: 0.1 });
  els.forEach(el => { el.classList.add('reveal-target'); obs.observe(el); });
}

// Auto-dismiss flash
function setupFlash() {
  setTimeout(() => {
    document.querySelectorAll('.flash').forEach(f => {
      f.style.cssText = 'opacity:0;transform:translateX(110%);transition:all .4s ease';
      setTimeout(() => f.remove(), 400);
    });
  }, 4500);
}

// Add reveal CSS dynamically
const style = document.createElement('style');
style.textContent = `
  .reveal-target{opacity:0;transform:translateY(22px);transition:opacity .5s ease,transform .5s ease}
  .reveal-target.revealed{opacity:1;transform:none}
`;
document.head.appendChild(style);

document.addEventListener('DOMContentLoaded', () => {
  updateCartCount();
  setupPayment();
  setupFAQ();
  setupStars();
  setupReveal();
  setupFlash();
});
