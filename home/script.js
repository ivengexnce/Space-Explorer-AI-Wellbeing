// script.js — OrbitX Home Page

/* ================================
   NAV TOGGLE
================================ */
const toggle = document.querySelector('.nav-toggle');
const navLinks = document.querySelector('.nav-links');

toggle && toggle.addEventListener('click', () => {
    toggle.classList.toggle('active');
    navLinks.classList.toggle('active');
});

// Close nav on link click (mobile)
navLinks && navLinks.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', () => {
        navLinks.classList.remove('active');
        toggle.classList.remove('active');
    });
});

// Close nav on outside click
document.addEventListener('click', (e) => {
    if (toggle && navLinks &&
        !toggle.contains(e.target) &&
        !navLinks.contains(e.target)) {
        navLinks.classList.remove('active');
        toggle.classList.remove('active');
    }
});

/* ================================
   NEWSLETTER FORM
================================ */
// Support both ID and class-based forms
const newsletterForms = document.querySelectorAll('#newsletterForm, .newsletter');

newsletterForms.forEach(form => {
    form.addEventListener('submit', e => {
        e.preventDefault();
        const btn = form.querySelector('button');
        if (btn) {
            const original = btn.textContent;
            btn.textContent = '✅ Subscribed!';
            btn.disabled = true;
            setTimeout(() => {
                btn.textContent = original;
                btn.disabled = false;
            }, 3000);
        }
        form.reset();
    });
});

/* ================================
   FAQ ACCORDION
================================ */
document.querySelectorAll('.faq-item').forEach(item => {
    const question = item.querySelector('h3');
    const answer = item.querySelector('p');

    // Wrap question in a clickable element if not already
    if (question && answer) {
        // Hide answers by default
        answer.style.overflow = 'hidden';
        answer.style.maxHeight = '0';
        answer.style.transition = 'max-height .4s ease, opacity .4s ease';
        answer.style.opacity = '0';
    }

    item.addEventListener('click', () => {
        const isOpen = item.classList.contains('active');

        // Close all others
        document.querySelectorAll('.faq-item').forEach(i => {
            i.classList.remove('active');
            const a = i.querySelector('p');
            if (a) { a.style.maxHeight = '0';
                a.style.opacity = '0'; }
        });

        // Open clicked
        if (!isOpen) {
            item.classList.add('active');
            if (answer) {
                answer.style.maxHeight = answer.scrollHeight + 'px';
                answer.style.opacity = '1';
            }
        }
    });
});

/* ================================
   SCROLL REVEAL (Intersection Observer)
================================ */
const observerOptions = {
    root: null,
    rootMargin: '0px',
    threshold: 0.12
};

const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('revealed');
            revealObserver.unobserve(entry.target);
        }
    });
}, observerOptions);

document.querySelectorAll(
    '.about-card, .explore-card, .faq-item'
).forEach(el => {
    el.classList.add('reveal-on-scroll');
    revealObserver.observe(el);
});

// Inject reveal CSS dynamically
const revealStyle = document.createElement('style');
revealStyle.textContent = `
    .reveal-on-scroll {
        opacity: 0;
        transform: translateY(24px);
        transition: opacity .7s ease, transform .7s ease;
    }
    .reveal-on-scroll.revealed {
        opacity: 1;
        transform: translateY(0);
    }
`;
document.head.appendChild(revealStyle);

/* ================================
   SMOOTH SCROLL for anchor links
================================ */
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', (e) => {
        const target = document.querySelector(anchor.getAttribute('href'));
        if (target) {
            e.preventDefault();
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    });
});