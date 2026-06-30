// Main JavaScript functionality for PPTEval website

document.addEventListener('DOMContentLoaded', function() {
    // Initialize all interactive features
    initSmoothScrolling();
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

`;
document.head.appendChild(style);

// Toggle difficulty breakdown rows
function toggleDetails(button) {
    const modelRow = button.closest('tr.model-row');
    if (!modelRow) return;
    const slug = modelRow.getAttribute('data-slug');
    const rows = document.querySelectorAll(`tr.difficulty-row[data-parent="${slug}"]`);
    const expanded = button.getAttribute('aria-expanded') === 'true';
    const modelName = modelRow.querySelector('.model-name')?.textContent.trim() || 'model';

    if (expanded) {
        rows.forEach(row => {
            row.classList.remove('show');
            row.setAttribute('aria-hidden', 'true');
        });
        button.setAttribute('aria-expanded', 'false');
        button.setAttribute('aria-label', `Show difficulty breakdown for ${modelName}`);
        button.textContent = '▸';
        modelRow.classList.remove('open');
    } else {
        rows.forEach(row => {
            row.classList.add('show');
            row.setAttribute('aria-hidden', 'false');
        });
        button.setAttribute('aria-expanded', 'true');
        button.setAttribute('aria-label', `Hide difficulty breakdown for ${modelName}`);
        button.textContent = '▾';
        modelRow.classList.add('open');
    }
}
window.toggleDetails = toggleDetails;

function initLeaderboardSorting() {
    const table = document.getElementById('leaderboard-table');
    if (!table || table.dataset.sortingInitialized === 'true') return;
    table.dataset.sortingInitialized = 'true';

    const sortButton = document.getElementById('sort-leaderboard');
    const tierSelect = document.getElementById('sort-tier');
    const metricSelect = document.getElementById('sort-metric');
    const applySort = () => sortLeaderboard(table, tierSelect, metricSelect);

    if (sortButton) sortButton.addEventListener('click', applySort);
    if (tierSelect) tierSelect.addEventListener('change', applySort);
    if (metricSelect) metricSelect.addEventListener('change', applySort);

    window.applySort = applySort;
    applySort();
}

function sortLeaderboard(table, tierSelect, metricSelect) {
    const tbody = table.querySelector('tbody');
    const tier = tierSelect ? tierSelect.value : 'overall';
    const metric = metricSelect ? metricSelect.value : 'success_rate';
    const suffixByMetric = {
        success_rate: 'success',
        avg_score: 'score',
        avg_steps: 'steps'
    };
    const overallAttributeByMetric = {
        success_rate: 'data-success-rate',
        avg_score: 'data-avg-score',
        avg_steps: 'data-avg-steps'
    };
    const attrKey = tier === 'overall'
        ? overallAttributeByMetric[metric]
        : `data-${tier}-${suffixByMetric[metric]}`;
    const ascending = metric === 'avg_steps';
    const modelRows = Array.from(tbody.querySelectorAll('tr.model-row'))
        .map((row, originalIndex) => ({ row, originalIndex }));

    modelRows.sort((aEntry, bEntry) => {
        const aVal = Number.parseFloat(aEntry.row.getAttribute(attrKey));
        const bVal = Number.parseFloat(bEntry.row.getAttribute(attrKey));
        const aMissing = Number.isNaN(aVal);
        const bMissing = Number.isNaN(bVal);

        if (aMissing !== bMissing) return aMissing ? 1 : -1;
        if (aMissing && bMissing) return aEntry.originalIndex - bEntry.originalIndex;

        const difference = ascending ? aVal - bVal : bVal - aVal;
        return difference || aEntry.originalIndex - bEntry.originalIndex;
    });

    const sortedGroups = document.createDocumentFragment();
    modelRows.forEach(({ row }) => {
        const slug = row.getAttribute('data-slug');
        const difficultyRows = Array.from(
            tbody.querySelectorAll(`tr.difficulty-row[data-parent="${slug}"]`)
        );
        sortedGroups.appendChild(row);
        difficultyRows.forEach(difficultyRow => sortedGroups.appendChild(difficultyRow));
    });
    tbody.appendChild(sortedGroups);
}

// Initialize immediately when possible, listen for DOM readiness when needed,
// and retry on the next task for pages that load this script after that event.
initLeaderboardSorting();
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initLeaderboardSorting, { once: true });
}
setTimeout(initLeaderboardSorting, 0);
