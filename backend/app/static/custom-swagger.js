// Custom JavaScript for Swagger UI enhancements

document.addEventListener('DOMContentLoaded', function() {
    // Add custom branding
    const topbar = document.querySelector('.topbar');
    if (topbar) {
        topbar.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: space-between; width: 100%;">
                <div style="display: flex; align-items: center; gap: 1rem;">
                    <div style="width: 40px; height: 40px; background: linear-gradient(135deg, #2563eb 0%, #10b981 100%); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: bold; color: white; font-size: 1.25rem;">
                        T
                    </div>
                    <div>
                        <div style="font-size: 1.25rem; font-weight: 700; color: #f9fafb;">Tempus</div>
                        <div style="font-size: 0.875rem; color: #94a3b8;">Ephemeral Preview Environments</div>
                    </div>
                </div>
                <div style="color: #94a3b8; font-size: 0.875rem;">
                    API v1.0.0
                </div>
            </div>
        `;
    }

    // Enhance operation blocks with icons
    const operationBlocks = document.querySelectorAll('.opblock');
    operationBlocks.forEach(block => {
        const method = block.classList.contains('opblock-post') ? 'POST' :
                      block.classList.contains('opblock-get') ? 'GET' :
                      block.classList.contains('opblock-put') ? 'PUT' :
                      block.classList.contains('opblock-delete') ? 'DELETE' : '';
        
        if (method) {
            const summary = block.querySelector('.opblock-summary');
            if (summary) {
                const methodElement = summary.querySelector('.opblock-summary-method');
                if (methodElement) {
                    methodElement.setAttribute('title', `${method} Request`);
                }
            }
        }
    });

    // Add smooth scroll behavior
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });

    // Enhance code copy functionality
    const codeBlocks = document.querySelectorAll('.highlight-code, .microlight');
    codeBlocks.forEach(block => {
        block.style.position = 'relative';
        block.addEventListener('mouseenter', function() {
            if (!this.querySelector('.copy-button')) {
                const copyBtn = document.createElement('button');
                copyBtn.className = 'copy-button';
                copyBtn.innerHTML = '📋';
                copyBtn.style.cssText = `
                    position: absolute;
                    top: 0.5rem;
                    right: 0.5rem;
                    background: rgba(37, 99, 235, 0.8);
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 0.25rem 0.5rem;
                    cursor: pointer;
                    font-size: 0.875rem;
                    transition: all 0.2s ease;
                `;
                copyBtn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    const text = block.textContent;
                    navigator.clipboard.writeText(text).then(() => {
                        copyBtn.innerHTML = '✓';
                        copyBtn.style.background = 'rgba(16, 185, 129, 0.8)';
                        setTimeout(() => {
                            copyBtn.innerHTML = '📋';
                            copyBtn.style.background = 'rgba(37, 99, 235, 0.8)';
                        }, 2000);
                    });
                });
                this.appendChild(copyBtn);
            }
        });
    });
});

