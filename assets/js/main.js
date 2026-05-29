// Main JavaScript functionality for PPTEval website

document.addEventListener('DOMContentLoaded', function() {
    // Initialize all interactive features
    initSmoothScrolling();
    initTableFiltering();
    initFAQAccordion();
    initBackToTop();
    initProgressAnimations();
});

// Smooth scrolling for navigation links
function initSmoothScrolling() {
    const links = document.querySelectorAll('a[href^="#"]');
    
    links.forEach(link => {
        link.addEventListener('click', function(e) {
            const href = this.getAttribute('href');
            
            if (href === '#' || href === '#top') {
                e.preventDefault();
                window.scrollTo({ top: 0, behavior: 'smooth' });
                return;
            }
            
            const target = document.querySelector(href);
            if (target) {
                e.preventDefault();
                const offsetTop = target.offsetTop - 80; // Account for fixed header
                window.scrollTo({ top: offsetTop, behavior: 'smooth' });
                
                // Update URL without triggering scroll
                history.pushState(null, null, href);
            }
        });
    });
}

// Table filtering functionality
// Legacy filtering removed; only sorting remains now.
function initTableFiltering() {
    const table = document.getElementById('benchmark-table');
    if (!table) return;
    // Expose a minimal sort function (overridden later for difficulty row handling)
    window.sortTable = function() {
        const tbody = table.querySelector('tbody');
        const modelRows = Array.from(tbody.querySelectorAll('tr.model-row'));
        modelRows.sort((a, b) => {
            const aRate = parseFloat(a.querySelector('.success-rate').textContent);
            const bRate = parseFloat(b.querySelector('.success-rate').textContent);
            return bRate - aRate;
        });
        modelRows.forEach(row => {
            tbody.appendChild(row);
            const slug = row.getAttribute('data-slug');
            const difficultyRows = Array.from(document.querySelectorAll(`tr.difficulty-row[data-parent="${slug}"]`));
            difficultyRows.forEach(dr => tbody.appendChild(dr));
        });
    };
}

function updateResultCount() {
    const table = document.getElementById('benchmark-table');
    if (!table) return;
    
    const visibleRows = table.querySelectorAll('tbody tr[style=""], tbody tr:not([style])');
    const totalRows = table.querySelectorAll('tbody tr').length;
    
    // Update or create result count display
    let countDisplay = document.querySelector('.result-count');
    if (!countDisplay) {
        countDisplay = document.createElement('div');
        countDisplay.className = 'result-count';
        table.parentNode.insertBefore(countDisplay, table);
    }
    
    countDisplay.textContent = `Showing ${visibleRows.length} of ${totalRows} results`;
}

// FAQ accordion functionality
function initFAQAccordion() {
    window.toggleFAQ = function(element) {
        const faqItem = element.parentElement;
        const answer = faqItem.querySelector('.faq-answer');
        const icon = element.querySelector('.faq-icon');
        
        // Close other open FAQs
        const allFAQs = document.querySelectorAll('.faq-item');
        allFAQs.forEach(item => {
            if (item !== faqItem) {
                const otherAnswer = item.querySelector('.faq-answer');
                const otherQuestion = item.querySelector('.faq-question');
                const otherIcon = item.querySelector('.faq-icon');
                
                otherAnswer.classList.remove('active');
                otherQuestion.classList.remove('active');
            }
        });
        
        // Toggle current FAQ
        const isActive = answer.classList.contains('active');
        
        if (isActive) {
            answer.classList.remove('active');
            element.classList.remove('active');
        } else {
            answer.classList.add('active');
            element.classList.add('active');
        }
    };
}

// Back to top button
function initBackToTop() {
    const backToTopBtn = document.getElementById('back-to-top');
    if (!backToTopBtn) return;
    
    window.addEventListener('scroll', function() {
        if (window.pageYOffset > 300) {
            backToTopBtn.classList.add('visible');
        } else {
            backToTopBtn.classList.remove('visible');
        }
    });
    
    backToTopBtn.addEventListener('click', function() {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
}



// Progress bar animations
function initProgressAnimations() {
    const progressBars = document.querySelectorAll('.progress-bar');
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const progressBar = entry.target;
                const width = progressBar.style.width;
                
                // Reset and animate
                progressBar.style.width = '0%';
                setTimeout(() => {
                    progressBar.style.width = width;
                }, 100);
            }
        });
    }, { threshold: 0.5 });
    
    progressBars.forEach(bar => {
        observer.observe(bar);
    });
}

// Utility functions
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Add fade-in animation on scroll
function initScrollAnimations() {
    const animatedElements = document.querySelectorAll('.card, .feature-card, .stat-card');
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('fade-in');
            }
        });
    }, { threshold: 0.1 });
    
    animatedElements.forEach(el => {
        observer.observe(el);
    });
}

// Initialize scroll animations when DOM is loaded
document.addEventListener('DOMContentLoaded', initScrollAnimations);

// BibTeX copy functionality
window.copyBibTeX = function() {
    const bibtexCode = document.getElementById('bibtex-code');
    if (!bibtexCode) return;
    
    const textArea = document.createElement('textarea');
    textArea.value = bibtexCode.textContent;
    document.body.appendChild(textArea);
    textArea.select();
    
    try {
        document.execCommand('copy');
        
        // Show success message
        const copyBtn = document.querySelector('.copy-btn');
        copyBtn.classList.add('copied');
        
        setTimeout(() => {
            copyBtn.classList.remove('copied');
        }, 2000);
        
    } catch (err) {
        console.error('Failed to copy BibTeX:', err);
    }
    
    document.body.removeChild(textArea);
};

// Enhanced screenshot gallery functionality
function initScreenshotGallery() {
    const screenshots = document.querySelectorAll('.screenshot-img');
    
    screenshots.forEach(img => {
        img.addEventListener('click', function() {
            // Create modal overlay
            const modal = document.createElement('div');
            modal.className = 'screenshot-modal';
            modal.innerHTML = `
                <div class="modal-backdrop" onclick="closeScreenshotModal()"></div>
                <div class="modal-content">
                    <img src="${this.src}" alt="${this.alt}" class="modal-img">
                    <button class="modal-close" onclick="closeScreenshotModal()">
                        <i class="fas fa-times"></i>
                    </button>
                    <p class="modal-caption">${this.nextElementSibling.textContent}</p>
                </div>
            `;
            
            document.body.appendChild(modal);
            document.body.style.overflow = 'hidden';
            
            // Animate in
            setTimeout(() => {
                modal.classList.add('active');
            }, 10);
        });
    });
}

window.closeScreenshotModal = function() {
    const modal = document.querySelector('.screenshot-modal');
    if (!modal) return;
    
    modal.classList.remove('active');
    setTimeout(() => {
        document.body.removeChild(modal);
        document.body.style.overflow = '';
    }, 300);
};

// Initialize screenshot gallery when DOM is loaded
document.addEventListener('DOMContentLoaded', initScreenshotGallery);

// Add CSS animation classes dynamically
const style = document.createElement('style');
style.textContent = `
    .fade-in {
        animation: fadeInUp 0.6s ease-out forwards;
    }
    
    @keyframes fadeInUp {
        from {
            opacity: 0;
            transform: translateY(30px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    .result-count {
        text-align: center;
        margin-bottom: 1rem;
        color: var(--text-muted);
        font-size: var(--font-size-sm);
    }
    
    .screenshot-modal {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        z-index: 9999;
        opacity: 0;
        transition: opacity 0.3s ease;
    }
    
    .screenshot-modal.active {
        opacity: 1;
    }
    
    .modal-backdrop {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background-color: rgba(0, 0, 0, 0.8);
    }
    
    .modal-content {
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        max-width: 90vw;
        max-height: 90vh;
        background: white;
        border-radius: var(--border-radius-lg);
        padding: var(--spacing-lg);
        text-align: center;
    }
    
    .modal-img {
        max-width: 100%;
        max-height: 70vh;
        border-radius: var(--border-radius);
    }
    
    .modal-close {
        position: absolute;
        top: var(--spacing-md);
        right: var(--spacing-md);
        background: var(--primary-color);
        color: white;
        border: none;
        border-radius: 50%;
        width: 40px;
        height: 40px;
        cursor: pointer;
        font-size: var(--font-size-lg);
    }
    
    .modal-caption {
        margin-top: var(--spacing-md);
        color: var(--text-muted);
        font-size: var(--font-size-sm);
    }

    /* Benchmark difficulty rows */
    .expand-btn { background: none; border: none; cursor: pointer; font-size: 14px; line-height: 1; padding: 4px 6px; color: var(--text-color); border-radius: 4px; }
    .expand-btn:hover { background: rgba(0,0,0,0.05); }
    .expand-btn:focus { outline: 2px solid var(--primary-color); outline-offset: 2px; }
    .expand-cell { text-align: center; }
    .difficulty-row { display: none; background: #fcfcfc; }
    .difficulty-row td { font-size: var(--font-size-sm); border-bottom: 1px solid #eee; }
    .difficulty-label { font-weight: 600; padding-left: 1.2rem; display: flex; align-items: center; gap: 0.55rem; line-height: 1.25; }
    .diff-dot { width: 9px; height: 9px; border-radius: 50%; flex: 0 0 9px; box-shadow: 0 0 0 2px #fff; }
    .diff-dot.easy { background:#4caf50; }
    .diff-dot.medium { background:#ff9800; }
    .diff-dot.hard { background:#f44336; }
    .indent { width: 28px; }
    .model-row td { border-bottom: 1px solid #ddd; }
    .model-row.open + .difficulty-row { /* first difficulty row after open model */ }
    .model-row.open .expand-btn { font-weight: 600; }
    .model-row.open .expand-btn::after { }
    .difficulty-row.easy .difficulty-label::before { background: #4caf50; }
    .difficulty-row.medium .difficulty-label::before { background: #ff9800; }
    .difficulty-row.hard .difficulty-label::before { background: #f44336; }
    .difficulty-row.show { display: table-row; animation: fadeInUp 0.3s ease; }
`;
document.head.appendChild(style);

// Toggle difficulty breakdown rows
function toggleDetails(button) {
    const modelRow = button.closest('tr.model-row');
    if (!modelRow) return;
    const slug = modelRow.getAttribute('data-slug');
    const rows = document.querySelectorAll(`tr.difficulty-row[data-parent="${slug}"]`);
    const expanded = button.getAttribute('aria-expanded') === 'true';

    if (expanded) {
        rows.forEach(r => r.classList.remove('show'));
        button.setAttribute('aria-expanded', 'false');
        button.textContent = '▸';
        modelRow.classList.remove('open');
    } else {
        rows.forEach(r => r.classList.add('show'));
        button.setAttribute('aria-expanded', 'true');
        button.textContent = '▾';
        modelRow.classList.add('open');
    }
}
window.toggleDetails = toggleDetails;

// New multi-criteria sorting
function applySort() {
    const table = document.getElementById('benchmark-table');
    if (!table) return;
    const tbody = table.querySelector('tbody');
    const tierSelect = document.getElementById('sort-tier');
    const metricSelect = document.getElementById('sort-metric');

    const tier = tierSelect ? tierSelect.value : 'overall';
    const metric = metricSelect ? metricSelect.value : 'avg_score';

    // Determine attribute key
    let attrKey;
    if (tier === 'overall') {
        if (metric === 'success_rate') attrKey = 'data-success-rate';
        else if (metric === 'avg_score') attrKey = 'data-avg-score';
        else if (metric === 'avg_steps') attrKey = 'data-avg-steps';
    } else {
        if (metric === 'success_rate') attrKey = `data-${tier}-success`;
        else if (metric === 'avg_score') attrKey = `data-${tier}-score`;
        else if (metric === 'avg_steps') attrKey = `data-${tier}-steps`;
    }

    const modelRows = Array.from(tbody.querySelectorAll('tr.model-row'));

    const ascending = metric === 'avg_steps';

    modelRows.sort((a, b) => {
        const aVal = parseFloat(a.getAttribute(attrKey));
        const bVal = parseFloat(b.getAttribute(attrKey));
        if (isNaN(aVal) && isNaN(bVal)) return 0;
        if (isNaN(aVal)) return 1;
        if (isNaN(bVal)) return -1;
        return ascending ? aVal - bVal : bVal - aVal;
    });

    // Reattach rows with their difficulty children
    modelRows.forEach(row => {
        tbody.appendChild(row);
        const slug = row.getAttribute('data-slug');
        const diffRows = Array.from(document.querySelectorAll(`tr.difficulty-row[data-parent="${slug}"]`));
        diffRows.forEach(dr => tbody.appendChild(dr));
    });
}
window.applySort = applySort;

// Default initial sort (Overall Avg Score desc)
document.addEventListener('DOMContentLoaded', () => {
    // Ensure selects reflect default
    const tierSelect = document.getElementById('sort-tier');
    const metricSelect = document.getElementById('sort-metric');
    if (tierSelect) tierSelect.value = 'overall';
    if (metricSelect) metricSelect.value = 'avg_score';
    applySort();
});