document.addEventListener('DOMContentLoaded', function() {
    console.log('Ground truth validation script loaded');
    
    // DOM Elements
    const fileInput = document.getElementById('csv-file');
    const uploadArea = document.getElementById('upload-area');
    const uploadText = document.getElementById('upload-text');
    const previewSection = document.getElementById('preview-section');
    const configSection = document.getElementById('config-section');
    const resultsSection = document.getElementById('results-section');
    const progressSection = document.getElementById('progress-section');
    const errorContainer = document.getElementById('error-container');
    const errorText = document.getElementById('error-text');
    
    // Model data
    let availableModels = [];
    let csvData = null;
    let processedResults = [];
    
    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // Fetch available models
    fetchModels();
    
    // File Upload Event Handlers
    uploadArea.addEventListener('click', function() {
        fileInput.click();
    });
    
    uploadArea.addEventListener('dragover', function(e) {
        e.preventDefault();
        e.stopPropagation();
        uploadArea.classList.add('drag-over');
    });
    
    uploadArea.addEventListener('dragleave', function(e) {
        e.preventDefault();
        e.stopPropagation();
        uploadArea.classList.remove('drag-over');
    });
    
    uploadArea.addEventListener('drop', function(e) {
        e.preventDefault();
        e.stopPropagation();
        uploadArea.classList.remove('drag-over');
        
        if (e.dataTransfer.files.length) {
            fileInput.files = e.dataTransfer.files;
            handleFileUpload(e.dataTransfer.files[0]);
        }
    });
    
    fileInput.addEventListener('change', function(e) {
        if (this.files.length) {
            handleFileUpload(this.files[0]);
        }
    });
    
    // File Processing
    function handleFileUpload(file) {
        console.log('Handling file upload:', file.name);
        uploadText.textContent = `Processing ${file.name}...`;
        
        if (file.type !== 'text/csv' && !file.name.endsWith('.csv')) {
            showError('Please upload a CSV file');
            resetUploadArea();
            return;
        }
        
        Papa.parse(file, {
            header: true,
            skipEmptyLines: true,
            complete: function(results) {
                console.log('CSV parsing complete:', results);
                
                if (results.errors.length > 0) {
                    showError('Error parsing CSV: ' + results.errors[0].message);
                    resetUploadArea();
                    return;
                }
                
                if (!validateCSVStructure(results.data)) {
                    showError('CSV must include "prompt" and "ground_truth" columns');
                    resetUploadArea();
                    return;
                }
                
                csvData = results.data;
                displayPreview(results.data);
                showConfigSection();
            },
            error: function(error) {
                console.error('Error parsing CSV:', error);
                showError('Error parsing CSV file: ' + error.message);
                resetUploadArea();
            }
        });
    }
    
    function validateCSVStructure(data) {
        if (data.length === 0) {
            return false;
        }
        
        const firstRow = data[0];
        return 'prompt' in firstRow && 'ground_truth' in firstRow;
    }
    
    function displayPreview(data) {
        const previewTable = document.getElementById('preview-table');
        const previewThead = document.getElementById('preview-thead');
        const previewTbody = document.getElementById('preview-tbody');
        
        // Clear previous content
        previewThead.innerHTML = '';
        previewTbody.innerHTML = '';
        
        // Create header row
        const headerRow = document.createElement('tr');
        const headers = Object.keys(data[0]);
        
        headers.forEach(header => {
            const th = document.createElement('th');
            th.textContent = header;
            headerRow.appendChild(th);
        });
        
        previewThead.appendChild(headerRow);
        
        // Create data rows (first 5 only)
        const previewData = data.slice(0, 5);
        
        previewData.forEach(row => {
            const tr = document.createElement('tr');
            
            headers.forEach(header => {
                const td = document.createElement('td');
                td.textContent = row[header].length > 100 ? 
                    row[header].substring(0, 100) + '...' : 
                    row[header];
                tr.appendChild(td);
            });
            
            previewTbody.appendChild(tr);
        });
        
        // Update row count
        document.getElementById('row-count').textContent = `${data.length} rows`;
        
        // Show preview section
        previewSection.classList.remove('hidden');
    }
    
    // API and Model Functions
    function fetchModels() {
        fetch('/api/llm-models/')
            .then(response => response.json())
            .then(data => {
                availableModels = data.models;
                populateModelSelects(data.models);
            })
            .catch(error => {
                console.error('Error fetching models:', error);
                // Fallback to some default models if API fails
                const fallbackModels = [
                    { id: 'gpt-4', name: 'GPT-4' },
                    { id: 'gpt-3.5-turbo', name: 'GPT-3.5 Turbo' },
                    { id: 'claude-3-opus', name: 'Claude 3 Opus' },
                    { id: 'claude-3-sonnet', name: 'Claude 3 Sonnet' }
                ];
                availableModels = fallbackModels;
                populateModelSelects(fallbackModels);
            });
    }
    
    function populateModelSelects(models) {
        const modelSelect = document.getElementById('model-select');
        const validationModelSelect = document.getElementById('validation-model-select');
        
        // Clear existing options
        modelSelect.innerHTML = '';
        validationModelSelect.innerHTML = '';
        
        // Add models to selects
        models.forEach(model => {
            const option = document.createElement('option');
            option.value = model.id;
            option.textContent = model.provider ? `${model.name} - ${model.provider}` : `${model.name} - Unknown Provider`;
            
            const validationOption = option.cloneNode(true);
            
            modelSelect.appendChild(option);
            validationModelSelect.appendChild(validationOption);
        });
        
        // Set default validation model to GPT-4 if available
        const gpt4Option = Array.from(validationModelSelect.options).find(option => 
            option.value.includes('gpt-4') || option.textContent.includes('GPT-4')
        );
        
        if (gpt4Option) {
            validationModelSelect.value = gpt4Option.value;
        }
    }
    
    // UI State Management
    function showConfigSection() {
        configSection.classList.remove('hidden');
        uploadArea.classList.add('hidden');
    }
    
    function resetUploadArea() {
        uploadText.textContent = 'Drag and drop a CSV file, or click to select';
        fileInput.value = '';
    }
    
    function showError(message) {
        errorText.textContent = message;
        errorContainer.classList.remove('hidden');
        errorContainer.style.display = 'flex';
        
        // Auto-hide error after 10 seconds
        setTimeout(() => {
            errorContainer.classList.add('hidden');
            setTimeout(() => {
                errorContainer.style.display = 'none';
            }, 300);
        }, 10000);
        
        // Animate progress bar
        const progressBar = errorContainer.querySelector('.progress-bar');
        progressBar.style.width = '0';
        
        // Force reflow to ensure animation works
        void errorContainer.offsetWidth;
        
        progressBar.style.width = '100%';
    }
    
    // Run Validation
    document.getElementById('run-button').addEventListener('click', function() {
        // Get the selected model's API name, not just the ID
        const modelSelectEl = document.getElementById('model-select');
        const validationModelSelectEl = document.getElementById('validation-model-select');
        const modelId = modelSelectEl.value;
        const validationModelId = validationModelSelectEl.value;

        // Find the selected model's API name
        const selectedModel = availableModels.find(m => m.id == modelId || m.name == modelId);
        const selectedModelName = selectedModel ? selectedModel.name : modelId;

        // For validation model, if needed in future
        const selectedValidationModel = availableModels.find(m => m.id == validationModelId || m.name == validationModelId);
        const selectedValidationModelName = selectedValidationModel ? selectedValidationModel.name : validationModelId;
        const numReplies = parseInt(document.getElementById('num-replies').value);
        const enableMultithreading = document.getElementById('enable-multithreading').checked;
        const batchSize = parseInt(document.getElementById('batch-size').value);
        
        if (!modelId || !validationModelId) {
            showError('Please select models for validation');
            return;
        }
        
        if (isNaN(numReplies) || numReplies < 1 || numReplies > 5) {
            showError('Number of replies must be between 1 and 5');
            return;
        }
        
        if (enableMultithreading && (isNaN(batchSize) || batchSize < 1 || batchSize > 20)) {
            showError('Batch size must be between 1 and 20');
            return;
        }
        
        // Hide config section and show progress
        configSection.classList.add('hidden');
        previewSection.classList.add('hidden');
        progressSection.classList.remove('hidden');
        
        // Start validation process
        // Use the model's API name for backend call
        runValidation(selectedModelName, selectedValidationModelName, numReplies, enableMultithreading, batchSize);
    });
    
    // --- UPDATED: Real Model Inference via API ---
    function runValidation(modelName, validationModelName, numReplies, enableMultithreading, batchSize) {
        const totalPrompts = csvData.length;
        let processedPrompts = 0;
        let startTime = Date.now();
        processedResults = [];
        updateProgress(0, totalPrompts);

        // Prepare data for API
        const prompts = csvData.map(row => row.prompt);
        const groundTruths = csvData.map(row => row.ground_truth);

        fetch('/api/ground-truth-validate/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            },
            body: JSON.stringify({
                prompts: prompts,
                ground_truths: groundTruths,
                model: modelName,
                validation_model: validationModelName,
                num_replies: numReplies,
                batch_size: batchSize
            })
        })
        .then(response => response.json())
        .then(data => {
            if (!data.success) {
                showError(data.error || 'Validation failed.');
                progressSection.classList.add('hidden');
                configSection.classList.remove('hidden');
                previewSection.classList.remove('hidden');
                return;
            }
            // Flatten results for table display (one row per reply)
            data.results.forEach((item, idx) => {
                const prompt = item.prompt;
                const groundTruth = item.ground_truth;
                (item.model_replies || []).forEach((replyObj, j) => {
                    processedResults.push({
                        prompt: prompt,
                        ground_truth: groundTruth,
                        model_reply: replyObj.model_reply,
                        similarity_score: '', // Optionally fill if backend provides
                        match_category: replyObj.match_category || '',
                        validation_reasoning: replyObj.validation_reasoning || ''
                    });
                });
                processedPrompts++;
                updateProgress(processedPrompts, totalPrompts, startTime);
            });
            displayResults();
        })
        .catch(error => {
            showError('Error during validation: ' + error.message);
            progressSection.classList.add('hidden');
            configSection.classList.remove('hidden');
            previewSection.classList.remove('hidden');
        });
    }

    function getCSRFToken() {
        const name = 'csrftoken';
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.startsWith(name + '=')) {
                return decodeURIComponent(cookie.substring(name.length + 1));
            }
        }
        return '';
    }
    // --- END UPDATED ---

    function updateProgress(current, total, startTime) {
        const percentage = Math.round((current / total) * 100);
        document.getElementById('progress-counter').textContent = `${current} of ${total}`;
        document.getElementById('progress-percentage').textContent = `${percentage}%`;
        document.getElementById('progress-value').style.width = `${percentage}%`;
        
        // Update estimated time
        if (startTime && current > 0) {
            const elapsedMs = Date.now() - startTime;
            const msPerPrompt = elapsedMs / current;
            const remainingPrompts = total - current;
            const remainingMs = msPerPrompt * remainingPrompts;
            
            let timeString = '';
            if (remainingMs > 3600000) {
                timeString = `~${Math.round(remainingMs / 3600000)} hours`;
            } else if (remainingMs > 60000) {
                timeString = `~${Math.round(remainingMs / 60000)} minutes`;
            } else {
                timeString = `~${Math.round(remainingMs / 1000)} seconds`;
            }
            
            document.getElementById('estimated-time').textContent = timeString;
        }
    }
    
    function getRandomMatchCategory() {
        const categories = [
            'exact_match', 'strong_match', 'moderate_match', 
            'weak_match', 'different', 'error'
        ];
        return categories[Math.floor(Math.random() * categories.length)];
    }
    
    // Results Display
    function displayResults() {
        progressSection.classList.add('hidden');
        resultsSection.classList.remove('hidden');
        
        // Display model name
        const modelSelect = document.getElementById('model-select');
        const selectedModelName = modelSelect.options[modelSelect.selectedIndex].text;
        document.getElementById('model-name-display').textContent = selectedModelName;
        
        // Set up results table
        setupResultsTable();
        
        // Set up pagination
        setupPagination();
        
        // Set up search functionality
        setupSearch();
        
        // Set up download buttons
        setupDownloadButtons();
    }
    
    function setupResultsTable() {
        const resultsTable = document.getElementById('results-table');
        const resultsThead = document.getElementById('results-thead');
        const resultsTbody = document.getElementById('results-tbody');
        
        // Clear previous content
        resultsThead.innerHTML = '';
        resultsTbody.innerHTML = '';
        
        // Create header row
        const headerRow = document.createElement('tr');
        const headers = ['#', 'Prompt', 'Ground Truth', 'Model Reply', 'Match'];
        
        headers.forEach(header => {
            const th = document.createElement('th');
            th.textContent = header;
            headerRow.appendChild(th);
        });
        
        resultsThead.appendChild(headerRow);
        
        // Display first page of results
        displayResultsPage(1);
    }
    
    function displayResultsPage(page) {
        const rowsPerPage = parseInt(document.getElementById('rows-per-page').value);
        const startIndex = (page - 1) * rowsPerPage;
        const endIndex = Math.min(startIndex + rowsPerPage, processedResults.length);
        const resultsTbody = document.getElementById('results-tbody');
        
        // Clear previous content
        resultsTbody.innerHTML = '';
        
        // Create data rows for current page
        for (let i = startIndex; i < endIndex; i++) {
            const result = processedResults[i];
            const tr = document.createElement('tr');
            
            // Row number
            const tdNum = document.createElement('td');
            tdNum.textContent = i + 1;
            tr.appendChild(tdNum);
            
            // Prompt
            const tdPrompt = document.createElement('td');
            tdPrompt.appendChild(createExpandableText(result.prompt));
            tr.appendChild(tdPrompt);
            
            // Ground Truth
            const tdGroundTruth = document.createElement('td');
            tdGroundTruth.appendChild(createExpandableText(result.ground_truth));
            tr.appendChild(tdGroundTruth);
            
            // Model Reply
            const tdModelReply = document.createElement('td');
            tdModelReply.appendChild(createExpandableText(result.model_reply));
            tr.appendChild(tdModelReply);
            
            // Match
            const tdMatch = document.createElement('td');
            tdMatch.appendChild(createMatchIndicator(result.match_category, result.similarity_score));
            
            // Add validation reasoning if available
            if (result.validation_reasoning) {
                const reasoningDiv = document.createElement('div');
                reasoningDiv.className = 'validation-reasoning';
                reasoningDiv.textContent = result.validation_reasoning;
                tdMatch.appendChild(reasoningDiv);
            }
            
            tr.appendChild(tdMatch);
            
            resultsTbody.appendChild(tr);
        }
        
        // Update pagination display
        document.getElementById('current-page-display').textContent = page;
    }
    
    function createExpandableText(text) {
        const container = document.createElement('div');
        
        if (text.length <= 100) {
            container.textContent = text;
            return container;
        }
        
        const preview = document.createElement('div');
        preview.className = 'text-preview';
        preview.textContent = text.substring(0, 100) + '...';
        
        const expandBtn = document.createElement('button');
        expandBtn.className = 'btn btn-link btn-sm expand-text p-0 ms-2';
        expandBtn.textContent = 'Show more';
        
        const fullText = document.createElement('div');
        fullText.className = 'full-text hidden';
        fullText.textContent = text;
        
        const collapseBtn = document.createElement('button');
        collapseBtn.className = 'btn btn-link btn-sm collapse-text p-0';
        collapseBtn.textContent = 'Show less';
        collapseBtn.style.display = 'none';
        
        expandBtn.addEventListener('click', function() {
            preview.classList.add('hidden');
            expandBtn.style.display = 'none';
            fullText.classList.remove('hidden');
            collapseBtn.style.display = 'inline';
        });
        
        collapseBtn.addEventListener('click', function() {
            preview.classList.remove('hidden');
            expandBtn.style.display = 'inline';
            fullText.classList.add('hidden');
            collapseBtn.style.display = 'none';
        });
        
        container.appendChild(preview);
        container.appendChild(expandBtn);
        container.appendChild(fullText);
        container.appendChild(collapseBtn);
        
        return container;
    }
    
    function createMatchIndicator(matchCategory, similarityScore) {
        const container = document.createElement('div');
        const indicator = document.createElement('span');
        
        switch (matchCategory) {
            case 'exact_match':
                indicator.className = 'match-exact';
                indicator.textContent = 'Exact Match';
                break;
            case 'strong_match':
                indicator.className = 'match-strong';
                indicator.textContent = 'Strong Match';
                break;
            case 'moderate_match':
                indicator.className = 'match-moderate';
                indicator.textContent = 'Moderate Match';
                break;
            case 'weak_match':
                indicator.className = 'match-weak';
                indicator.textContent = 'Weak Match';
                break;
            case 'different':
                indicator.className = 'match-different';
                indicator.textContent = 'Different';
                break;
            case 'error':
                indicator.className = 'match-error';
                indicator.textContent = 'Error';
                break;
            default:
                indicator.className = 'match-error';
                indicator.textContent = 'Unknown';
        }
        
        container.appendChild(indicator);
        
        if (similarityScore) {
            const score = document.createElement('span');
            score.className = 'similarity-score';
            score.textContent = `(${similarityScore})`;
            container.appendChild(score);
        }
        
        return container;
    }
    
    function setupPagination() {
        const rowsPerPage = parseInt(document.getElementById('rows-per-page').value);
        const totalPages = Math.ceil(processedResults.length / rowsPerPage);
        const paginationControls = document.getElementById('pagination-controls');
        
        // Clear previous pagination
        paginationControls.innerHTML = '';
        
        // Update total pages display
        document.getElementById('total-pages-display').textContent = totalPages;
        
        // Show pagination if we have results
        if (processedResults.length > 0) {
            document.getElementById('pagination').classList.remove('hidden');
        }
        
        // Create pagination buttons
        const createPageBtn = (page, text, isActive = false) => {
            const btn = document.createElement('button');
            btn.className = `btn btn-sm ${isActive ? 'btn-primary' : 'btn-outline-secondary'}`;
            btn.textContent = text;
            btn.addEventListener('click', () => {
                displayResultsPage(page);
                updatePaginationButtons(page);
            });
            return btn;
        };
        
        // First page button
        paginationControls.appendChild(createPageBtn(1, '«'));
        
        // Previous page button
        paginationControls.appendChild(createPageBtn(
            Math.max(1, parseInt(document.getElementById('current-page-display').textContent) - 1),
            '‹'
        ));
        
        // Page number buttons
        const currentPage = parseInt(document.getElementById('current-page-display').textContent);
        const startPage = Math.max(1, currentPage - 2);
        const endPage = Math.min(totalPages, startPage + 4);
        
        for (let i = startPage; i <= endPage; i++) {
            paginationControls.appendChild(createPageBtn(i, i.toString(), i === currentPage));
        }
        
        // Next page button
        paginationControls.appendChild(createPageBtn(
            Math.min(totalPages, parseInt(document.getElementById('current-page-display').textContent) + 1),
            '›'
        ));
        
        // Last page button
        paginationControls.appendChild(createPageBtn(totalPages, '»'));
    }
    
    function updatePaginationButtons(currentPage) {
        const paginationButtons = document.getElementById('pagination-controls').children;
        const totalPages = parseInt(document.getElementById('total-pages-display').textContent);
        
        // Update current page display
        document.getElementById('current-page-display').textContent = currentPage;
        
        // Update previous and next buttons
        paginationButtons[1].addEventListener('click', () => {
            displayResultsPage(Math.max(1, currentPage - 1));
            updatePaginationButtons(Math.max(1, currentPage - 1));
        });
        
        paginationButtons[paginationButtons.length - 2].addEventListener('click', () => {
            displayResultsPage(Math.min(totalPages, currentPage + 1));
            updatePaginationButtons(Math.min(totalPages, currentPage + 1));
        });
        
        // Recreate page number buttons
        const paginationControls = document.getElementById('pagination-controls');
        
        // Remove old page number buttons
        while (paginationControls.children.length > 4) {
            paginationControls.removeChild(paginationControls.children[2]);
        }
        
        // Create new page number buttons
        const startPage = Math.max(1, currentPage - 2);
        const endPage = Math.min(totalPages, startPage + 4);
        
        for (let i = endPage; i >= startPage; i--) {
            const btn = document.createElement('button');
            btn.className = `btn btn-sm ${i === currentPage ? 'btn-primary' : 'btn-outline-secondary'}`;
            btn.textContent = i.toString();
            btn.addEventListener('click', () => {
                displayResultsPage(i);
                updatePaginationButtons(i);
            });
            
            paginationControls.insertBefore(btn, paginationControls.children[2]);
        }
    }
    
    // Rows per page change handler
    document.getElementById('rows-per-page').addEventListener('change', function() {
        displayResultsPage(1);
        setupPagination();
    });
    
    function setupSearch() {
        const searchInput = document.getElementById('search-input');
        
        searchInput.addEventListener('input', function() {
            const searchTerm = this.value.toLowerCase();
            
            if (searchTerm.length < 2) {
                // If search term is too short, show original results
                displayResultsPage(1);
                setupPagination();
                return;
            }
            
            // Filter results
            const filteredResults = processedResults.filter(result => 
                result.prompt.toLowerCase().includes(searchTerm) ||
                result.ground_truth.toLowerCase().includes(searchTerm) ||
                result.model_reply.toLowerCase().includes(searchTerm)
            );
            
            // Display filtered results
            displayFilteredResults(filteredResults);
        });
    }
    
    function displayFilteredResults(filteredResults) {
        const resultsTbody = document.getElementById('results-tbody');
        
        // Clear previous content
        resultsTbody.innerHTML = '';
        
        // Hide pagination for search results
        document.getElementById('pagination').classList.add('hidden');
        
        if (filteredResults.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 5;
            td.textContent = 'No matching results found';
            td.className = 'text-center py-3';
            tr.appendChild(td);
            resultsTbody.appendChild(tr);
            return;
        }
        
        // Create data rows for filtered results
        filteredResults.forEach((result, index) => {
            const tr = document.createElement('tr');
            
            // Row number
            const tdNum = document.createElement('td');
            tdNum.textContent = index + 1;
            tr.appendChild(tdNum);
            
            // Prompt
            const tdPrompt = document.createElement('td');
            tdPrompt.appendChild(createExpandableText(result.prompt));
            tr.appendChild(tdPrompt);
            
            // Ground Truth
            const tdGroundTruth = document.createElement('td');
            tdGroundTruth.appendChild(createExpandableText(result.ground_truth));
            tr.appendChild(tdGroundTruth);
            
            // Model Reply
            const tdModelReply = document.createElement('td');
            tdModelReply.appendChild(createExpandableText(result.model_reply));
            tr.appendChild(tdModelReply);
            
            // Match
            const tdMatch = document.createElement('td');
            tdMatch.appendChild(createMatchIndicator(result.match_category, result.similarity_score));
            
            // Add validation reasoning if available
            if (result.validation_reasoning) {
                const reasoningDiv = document.createElement('div');
                reasoningDiv.className = 'validation-reasoning';
                reasoningDiv.textContent = result.validation_reasoning;
                tdMatch.appendChild(reasoningDiv);
            }
            
            tr.appendChild(tdMatch);
            
            resultsTbody.appendChild(tr);
        });
    }
    
    function setupDownloadButtons() {
        // CSV Download
        document.getElementById('download-button').addEventListener('click', function() {
            const csvContent = convertResultsToCSV();
            downloadFile(csvContent, 'ground_truth_validation_results.csv', 'text/csv');
        });
        
        // JSON Download
        document.getElementById('download-json-button').addEventListener('click', function() {
            const jsonContent = JSON.stringify(processedResults, null, 2);
            downloadFile(jsonContent, 'ground_truth_validation_results.json', 'application/json');
        });
    }
    
    function convertResultsToCSV() {
        const headers = ['prompt', 'ground_truth', 'model_reply', 'similarity_score', 'match_category', 'validation_reasoning'];
        
        const csvRows = [
            headers.join(',')
        ];
        
        processedResults.forEach(result => {
            const values = headers.map(header => {
                const value = result[header] || '';
                // Escape quotes and wrap in quotes if contains comma or newline
                return `"${value.toString().replace(/"/g, '""')}"`;
            });
            csvRows.push(values.join(','));
        });
        
        return csvRows.join('\n');
    }
    
    function downloadFile(content, fileName, contentType) {
        const blob = new Blob([content], { type: contentType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }
    
    // Cancel and Minimize Progress
    document.getElementById('cancel-processing').addEventListener('click', function() {
        if (confirm('Are you sure you want to cancel the validation process?')) {
            progressSection.classList.add('hidden');
            configSection.classList.remove('hidden');
            previewSection.classList.remove('hidden');
        }
    });
    
    document.getElementById('minimize-progress').addEventListener('click', function() {
        progressSection.classList.toggle('minimized');
        this.innerHTML = progressSection.classList.contains('minimized') ?
            '<i class="bi bi-arrows-expand"></i> Expand' :
            '<i class="bi bi-arrows-collapse"></i> Minimize';
    });
    
    // Run Again Button
    document.getElementById('run-again-button').addEventListener('click', function() {
        resultsSection.classList.add('hidden');
        uploadArea.classList.remove('hidden');
        previewSection.classList.add('hidden');
        configSection.classList.add('hidden');
        resetUploadArea();
        processedResults = [];
    });
    
    // Export Report Button
    document.getElementById('export-report-button').addEventListener('click', function() {
        alert('Report export functionality will be implemented in a future update.');
    });
});
