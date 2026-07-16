document.addEventListener('DOMContentLoaded', function () {
    // ----------------------------
    // Shared upload handler
    // ----------------------------
    function setupUpload(fileInputElem, statusElem, editorElem) {
        if (!fileInputElem) return;
        fileInputElem.addEventListener('change', function (e) {
            const file = e.target.files[0];
            if (!file) return;
            const formData = new FormData();
            formData.append('document', file);
            statusElem.textContent = 'Uploading...';
            statusElem.style.color = '#FFD166';

            fetch('/upload_document', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    statusElem.textContent = 'Error: ' + data.error;
                    statusElem.style.color = '#d9534f';
                    return;
                }
                editorElem.value = data.editor_text;
                statusElem.textContent = '✔ Document loaded!';
                statusElem.style.color = '#6AB04C';

                const select = document.getElementById('paragraph-select');
                if (select && data.paragraphs && data.citable_indices) {
                    select.innerHTML = '';
                    const citable = data.citable_indices;
                    for (let i = 0; i < citable.length; i++) {
                        const idx = citable[i];
                        const text = data.paragraphs[idx] || '';
                        const preview = text.substring(0, 60) + (text.length > 60 ? '...' : '');
                        const option = document.createElement('option');
                        option.value = idx;
                        option.textContent = 'Paragraph ' + (i+1) + ': ' + preview;
                        select.appendChild(option);
                    }
                }
                const paperCard = document.getElementById('paper-card');
                if (paperCard) paperCard.style.display = 'none';
                const fetchStatus = document.getElementById('fetch-status');
                if (fetchStatus) fetchStatus.textContent = '';
            })
            .catch(err => {
                statusElem.textContent = 'Network error: ' + err.message;
                statusElem.style.color = '#d9534f';
            });
            fileInputElem.value = '';
        });
    }

    const editor = document.getElementById('editor-text');
    const uploadStatus = document.getElementById('upload-status');
    const fileInput = document.getElementById('file-upload');
    setupUpload(fileInput, uploadStatus, editor);

    const proofEditor = document.getElementById('editor-text-proof');
    const proofUploadStatus = document.getElementById('upload-status-proof');
    const proofFileInput = document.getElementById('file-upload-proof');
    setupUpload(proofFileInput, proofUploadStatus, proofEditor || editor);

    // ----------------------------
    // Citation mode
    // ----------------------------
    const fetchBtn = document.getElementById('fetch-btn');
    const paperCard = document.getElementById('paper-card');
    const fetchStatus = document.getElementById('fetch-status');
    const bibliographyList = document.getElementById('bibliography-list');
    const paragraphSelect = document.getElementById('paragraph-select');

    if (fetchBtn) {
        fetchBtn.addEventListener('click', function () {
            const selectedIndex = parseInt(paragraphSelect.value);
            const text = editor ? editor.value : '';
            if (isNaN(selectedIndex) || selectedIndex < 0) {
                fetchStatus.textContent = 'Please select a valid paragraph.';
                return;
            }

            fetchStatus.textContent = 'Analyzing and fetching papers...';
            fetchBtn.disabled = true;

            fetch('/fetch_paper', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    editor_text: text,
                    paragraph_index: selectedIndex
                })
            })
            .then(response => response.json())
            .then(data => {
                fetchBtn.disabled = false;
                if (data.error) {
                    fetchStatus.textContent = 'Error: ' + data.error;
                    if (paperCard) paperCard.style.display = 'none';
                    return;
                }
                const papers = data.papers;
                if (!papers || papers.length === 0) {
                    fetchStatus.textContent = 'No papers returned.';
                    if (paperCard) paperCard.style.display = 'none';
                    return;
                }
                
                fetchStatus.textContent = `${papers.length} papers fetched successfully!`;
                
                let html = '';
                papers.forEach((paper, index) => {
                    const authors = paper.authors.map(a => a.name).join(', ');
                    const abstract = paper.abstract ? paper.abstract.substring(0, 200) + (paper.abstract.length > 200 ? '...' : '') : 'No abstract available.';
                    html += `
                        <div class="paper-card-content" style="margin-bottom: 1.5rem; border-bottom: 2px solid #e8e2d7; padding-bottom: 1rem;">
                            <h4>${paper.title}</h4>
                            <p class="authors"><i class="fas fa-user"></i> ${authors}</p>
                            <p><i class="fas fa-university"></i> Venue: ${paper.venue} &nbsp;|&nbsp; Year: ${paper.year}</p>
                            <p class="abstract">${abstract}</p>
                    `;
                    if (paper.url) {
                        html += `<a href="${paper.url}" target="_blank" class="paper-link"><i class="fas fa-external-link-alt"></i> View on Crossref</a>`;
                    }
                    html += `
                            <div class="insertion-controls" style="margin-top: 0.8rem;">
                                <label>Format:</label>
                                <select class="insertion-mode" data-index="${index}">
                                    <option value="Only Citation">Only Citation</option>
                                    <option value="Insert Quote + Citation">Quote + Citation</option>
                                </select>
                                <button class="btn btn-success insert-btn" data-index="${index}"><i class="fas fa-plus-circle"></i> Insert</button>
                            </div>
                        </div>
                    `;
                });
                
                paperCard.innerHTML = html;
                paperCard.style.display = 'block';
                
                // Attach click handlers to dynamically created buttons
                paperCard.querySelectorAll('.insert-btn').forEach(btn => {
                    btn.addEventListener('click', function() {
                        const idx = this.getAttribute('data-index');
                        insertHandler(parseInt(idx));
                    });
                });

                const queryInfo = document.querySelector('.query-info');
                if (queryInfo) {
                    queryInfo.innerHTML = 'Last query: <code>' + (data.query || '') + '</code>';
                }
                const errorDiv = document.querySelector('.error-message');
                if (errorDiv) errorDiv.remove();
            })
            .catch(err => {
                fetchBtn.disabled = false;
                fetchStatus.textContent = 'Network error: ' + err.message;
                if (paperCard) paperCard.style.display = 'none';
            });
        });
    }

    function insertHandler(paperIndex) {
        const selectedIndex = parseInt(paragraphSelect.value);
        const text = editor ? editor.value : '';
        
        // Cible infailliblement la valeur sélectionnée par l'utilisateur
        const modeSelect = document.querySelector(`.insertion-mode[data-index="${paperIndex}"]`);
        const mode = modeSelect ? modeSelect.value : 'Only Citation';

        if (isNaN(selectedIndex) || selectedIndex < 0) {
            alert('Please select a valid paragraph.');
            return;
        }

        const allInsertBtns = document.querySelectorAll('.insert-btn');
        allInsertBtns.forEach(btn => btn.disabled = true);

        fetch('/insert_citation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                editor_text: text,
                paragraph_index: selectedIndex,
                insertion_mode: mode,
                paper_index: paperIndex
            })
        })
        .then(response => response.json())
        .then(data => {
            allInsertBtns.forEach(btn => btn.disabled = false);
            if (data.error) {
                alert('Error: ' + data.error);
                return;
            }
            editor.value = data.editor_text;
            if (data.bibliography && data.bibliography.length > 0) {
                let ul = bibliographyList.querySelector('ul');
                if (!ul) {
                    ul = document.createElement('ul');
                    bibliographyList.innerHTML = '';
                    bibliographyList.appendChild(ul);
                }
                ul.innerHTML = data.bibliography.map(function(entry) {
                    return '<li>' + entry.reference + '</li>';
                }).join('');
            } else {
                bibliographyList.innerHTML = '<p class="info">No citations inserted yet.</p>';
            }
        })
        .catch(err => {
            allInsertBtns.forEach(btn => btn.disabled = false);
            alert('Network error: ' + err.message);
        });
    }

    if (paperCard) {
        paperCard.querySelectorAll('.insert-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const idx = this.getAttribute('data-index');
                insertHandler(parseInt(idx));
            });
        });
    }

    // ----------------------------
    // Proofreading mode
    // ----------------------------
    const proofreadBtn = document.getElementById('proofread-btn');
    const resultDiv = document.getElementById('proofreading-result');
    const diffDisplay = document.getElementById('diff-display');
    const originalDisplay = document.getElementById('original-text-display');
    const diffStats = document.getElementById('diff-stats');
    const toggleBtn = document.getElementById('toggle-original-btn');
    const applyBtn = document.getElementById('apply-proofreading');
    const discardBtn = document.getElementById('discard-proofreading');
    const progressContainer = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');

    let originalText = '';
    let revisedText = '';
    let progressInterval = null;

    if (proofreadBtn) {
        proofreadBtn.addEventListener('click', function () {
            const text = proofEditor ? proofEditor.value : '';
            if (!text.trim()) {
                alert('Please write or paste some text to proofread.');
                return;
            }

            progressContainer.style.display = 'block';
            progressBar.style.width = '0%';
            progressText.textContent = '⏳ Analyzing your document...';
            let progress = 0;
            if (progressInterval) clearInterval(progressInterval);
            progressInterval = setInterval(function() {
                if (progress < 90) {
                    progress += Math.random() * 8 + 2;
                    if (progress > 90) progress = 90;
                    progressBar.style.width = progress + '%';
                }
            }, 300);

            proofreadBtn.disabled = true;
            proofreadBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';

            fetch('/proofread', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: text })
            })
            .then(response => response.json())
            .then(function(data) {
                clearInterval(progressInterval);
                progressBar.style.width = '100%';
                progressText.textContent = '✅ Done!';
                setTimeout(function() {
                    progressContainer.style.display = 'none';
                }, 800);

                proofreadBtn.disabled = false;
                proofreadBtn.innerHTML = '<i class="fas fa-wand-magic"></i> Proofread Document';

                if (data.error) {
                    alert('Error: ' + data.error);
                    return;
                }
                originalText = data.original_text;
                revisedText = data.revised_text;
                diffDisplay.innerHTML = data.diff_html;
                originalDisplay.textContent = originalText;
                originalDisplay.style.display = 'none';
                toggleBtn.textContent = 'Show Original';
                diffStats.innerHTML = '✨ Changes detected';
                resultDiv.style.display = 'block';
            })
            .catch(function(err) {
                clearInterval(progressInterval);
                progressContainer.style.display = 'none';
                proofreadBtn.disabled = false;
                proofreadBtn.innerHTML = '<i class="fas fa-wand-magic"></i> Proofread Document';
                alert('Network error: ' + err.message);
            });
        });
    }

    if (toggleBtn) {
        toggleBtn.addEventListener('click', function () {
            if (originalDisplay.style.display === 'none') {
                originalDisplay.style.display = 'block';
                toggleBtn.textContent = 'Hide Original';
            } else {
                originalDisplay.style.display = 'none';
                toggleBtn.textContent = 'Show Original';
            }
        });
    }

    if (applyBtn) {
        applyBtn.addEventListener('click', function () {
            if (proofEditor) {
                const newText = revisedText;
                proofEditor.value = newText;
                if (editor) editor.value = newText;
                fetch('/update_text', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: newText })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        const successDiv = document.getElementById('apply-success');
                        if (successDiv) {
                            successDiv.style.display = 'block';
                        }
                        applyBtn.style.display = 'none';
                        discardBtn.style.display = 'none';
                    } else {
                        alert('Error updating document.');
                    }
                })
                .catch(err => {
                    alert('Network error: ' + err.message);
                });
            }
        });
    }

    if (discardBtn) {
        discardBtn.addEventListener('click', function () {
            resultDiv.style.display = 'none';
        });
    }
});