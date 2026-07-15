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
                        option.textContent = `Paragraph ${i+1}: ${preview}`;
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
    // Citation mode (unchanged)
    // ----------------------------
    const fetchBtn = document.getElementById('fetch-btn');
    const insertBtn = document.getElementById('insert-btn');
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

            fetchStatus.textContent = 'Analyzing and fetching paper...';
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
                const paper = data.paper;
                if (!paper) {
                    fetchStatus.textContent = 'No paper returned.';
                    if (paperCard) paperCard.style.display = 'none';
                    return;
                }
                fetchStatus.textContent = 'Paper fetched successfully!';
                const authors = paper.authors.map(a => a.name).join(', ');
                const abstract = paper.abstract ? paper.abstract.substring(0, 250) + (paper.abstract.length > 250 ? '...' : '') : 'No abstract available.';
                let html = `
                    <div class="paper-card-content">
                        <h4>${paper.title}</h4>
                        <p class="authors"><i class="fas fa-user"></i> ${authors}</p>
                        <p><i class="fas fa-university"></i> Venue: ${paper.venue} &nbsp;|&nbsp; Year: ${paper.year}</p>
                        <p class="abstract">${abstract}</p>
                `;
                if (paper.url) {
                    html += `<a href="${paper.url}" target="_blank" class="paper-link"><i class="fas fa-external-link-alt"></i> View on Crossref</a>`;
                }
                html += `
                        <hr>
                        <div class="insertion-controls">
                            <label for="insertion-mode">Inline citation format:</label>
                            <select id="insertion-mode">
                                <option value="Only Citation">Only Citation</option>
                                <option value="Insert Quote + Citation">Insert Quote + Citation</option>
                            </select>
                            <button id="insert-btn" class="btn btn-success"><i class="fas fa-plus-circle"></i> Insert Citation</button>
                        </div>
                    </div>
                `;
                paperCard.innerHTML = html;
                paperCard.style.display = 'block';
                const newInsertBtn = paperCard.querySelector('#insert-btn');
                if (newInsertBtn) {
                    newInsertBtn.addEventListener('click', insertHandler);
                }
                const queryInfo = document.querySelector('.query-info');
                if (queryInfo) {
                    queryInfo.innerHTML = `Last query: <code>${data.query || ''}</code>`;
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

    function insertHandler() {
        const selectedIndex = parseInt(paragraphSelect.value);
        const text = editor ? editor.value : '';
        const modeSelect = document.getElementById('insertion-mode');
        const mode = modeSelect ? modeSelect.value : 'Only Citation';
        if (isNaN(selectedIndex) || selectedIndex < 0) {
            alert('Please select a valid paragraph.');
            return;
        }

        const insertBtnLocal = document.getElementById('insert-btn');
        if (insertBtnLocal) insertBtnLocal.disabled = true;

        fetch('/insert_citation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                editor_text: text,
                paragraph_index: selectedIndex,
                insertion_mode: mode
            })
        })
        .then(response => response.json())
        .then(data => {
            if (insertBtnLocal) insertBtnLocal.disabled = false;
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
                ul.innerHTML = data.bibliography.map(entry =>
                    `<li>${entry.reference}</li>`
                ).join('');
            } else {
                bibliographyList.innerHTML = '<p class="info">No citations inserted yet. Insert a citation to populate your bibliography.</p>';
            }
        })
        .catch(err => {
            if (insertBtnLocal) insertBtnLocal.disabled = false;
            alert('Network error: ' + err.message);
        });
    }

    const initialInsertBtn = document.querySelector('#insert-btn');
    if (initialInsertBtn) {
        initialInsertBtn.addEventListener('click', insertHandler);
    }

    // ----------------------------
    // Proofreading mode with server-side diff
    // ----------------------------
    const proofreadBtn = document.getElementById('proofread-btn');
    const resultDiv = document.getElementById('proofreading-result');
    const diffDisplay = document.getElementById('diff-display');
    const originalDisplay = document.getElementById('original-text-display');
    const diffStats = document.getElementById('diff-stats');
    const toggleBtn = document.getElementById('toggle-original-btn');
    const applyBtn = document.getElementById('apply-proofreading');
    const discardBtn = document.getElementById('discard-proofreading');

    let originalText = '';
    let revisedText = '';

    if (proofreadBtn) {
        proofreadBtn.addEventListener('click', function () {
            const text = proofEditor ? proofEditor.value : '';
            if (!text.trim()) {
                alert('Please write or paste some text to proofread.');
                return;
            }
            proofreadBtn.disabled = true;
            proofreadBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analyzing...';

            fetch('/proofread', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: text })
            })
            .then(response => response.json())
            .then(data => {
                proofreadBtn.disabled = false;
                proofreadBtn.innerHTML = '<i class="fas fa-wand-magic"></i> Proofread Document';
                if (data.error) {
                    alert('Error: ' + data.error);
                    return;
                }
                originalText = data.original_text;
                revisedText = data.revised_text;
                // Display diff HTML
                diffDisplay.innerHTML = data.diff_html;
                // Store original text for toggle
                originalDisplay.textContent = originalText;
                originalDisplay.style.display = 'none';
                toggleBtn.textContent = 'Show Original';
                diffStats.innerHTML = 'Diff generated.';
                resultDiv.style.display = 'block';
            })
            .catch(err => {
                proofreadBtn.disabled = false;
                proofreadBtn.innerHTML = '<i class="fas fa-wand-magic"></i> Proofread Document';
                alert('Network error: ' + err.message);
            });
        });
    }

    // Toggle original
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

    // Apply changes
    if (applyBtn) {
        applyBtn.addEventListener('click', function () {
            if (proofEditor) {
                proofEditor.value = revisedText;
                if (editor) editor.value = revisedText;
            }
            resultDiv.style.display = 'none';
        });
    }

    // Discard
    if (discardBtn) {
        discardBtn.addEventListener('click', function () {
            resultDiv.style.display = 'none';
        });
    }
});