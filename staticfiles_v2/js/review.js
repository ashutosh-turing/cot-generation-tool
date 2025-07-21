document.addEventListener("DOMContentLoaded", function () {
  const modelsList = document.getElementById("llm-models-list");
  const refreshModelsBtn = document.getElementById("refresh-models-btn");
  const fetchColabBtn = document.getElementById("fetch-colab-btn");
  const colabLinkInput = document.getElementById("colab-link");
  const colabStatus = document.getElementById("colab-fetch-status");
  const colabContentContainer = document.getElementById("colab-content-markdown");
  const runReviewBtn = document.getElementById("run-review-btn");
  const reviewResultsSection = document.getElementById("review-results-section");
  const additionalContextTextarea = document.getElementById("additional-context");
  const temperatureSlider = document.getElementById("temperature-slider");
  const temperatureValue = document.getElementById("temperature-value");

  let colabRawContent = "";
  let colabMarkdown = "";

  // Temperature slider functionality
  if (temperatureSlider && temperatureValue) {
    temperatureSlider.addEventListener("input", function() {
      temperatureValue.textContent = parseFloat(this.value).toFixed(1);
    });
  }

  // Validation function to check if requirements are met
  function validateRequirements() {
    const hasColabContent = colabRawContent && colabRawContent.trim().length > 0;
    const selectedModels = modelsList ? modelsList.querySelectorAll("input[type=checkbox]:checked") : [];
    const hasSelectedModels = selectedModels.length > 0;
    
    const runButton = document.getElementById("run-review-btn");
    const validationMessage = document.getElementById("validation-message");
    
    // Check if elements exist before trying to modify them
    if (!runButton || !validationMessage) {
      console.warn("Required elements not found for validation");
      return;
    }
    
    if (hasColabContent && hasSelectedModels) {
      // Requirements met - enable button
      runButton.disabled = false;
      validationMessage.innerHTML = '<i class="fas fa-check-circle text-green-500 mr-1"></i>Ready to run analysis';
      validationMessage.className = "mt-3 text-sm text-center text-green-600";
    } else {
      // Requirements not met - disable button and show appropriate message
      runButton.disabled = true;
      let message = "Please ";
      let missingItems = [];
      
      if (!hasColabContent) {
        missingItems.push("fetch Colab content");
      }
      if (!hasSelectedModels) {
        missingItems.push("select at least one LLM model");
      }
      
      message += missingItems.join(" and ") + " to proceed";
      
      validationMessage.innerHTML = '<i class="fas fa-exclamation-triangle text-amber-500 mr-1"></i>' + message;
      validationMessage.className = "mt-3 text-sm text-center text-gray-500";
    }
  }

  // Utility: Get CSRF token from cookie
  function getCSRFToken() {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      const cookies = document.cookie.split(";");
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, 10) === "csrftoken=") {
          cookieValue = decodeURIComponent(cookie.substring(10));
          break;
        }
      }
    }
    return cookieValue;
  }

  // Load LLM models
  function loadModels() {
    if (!modelsList) {
      console.error("Models list element not found");
      return;
    }
    
    modelsList.innerHTML = `
      <div class="flex items-center justify-center py-8">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        <span class="ml-3 text-gray-500">Loading models...</span>
      </div>
    `;
    
    fetch("/api/llm-models/")
      .then((res) => res.json())
      .then((data) => {
        modelsList.innerHTML = "";
        if (data.models && data.models.length > 0) {
          data.models.forEach((model) => {
            const modelCard = document.createElement("div");
            modelCard.className = "flex items-center p-3 border border-gray-200 rounded-xl hover:border-blue-300 hover:bg-blue-50 transition-all duration-200 cursor-pointer";
            
            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.className = "model-checkbox h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded";
            checkbox.value = model.id;
            checkbox.name = "llm_model";
            checkbox.id = `model-${model.id}`;
            
            const label = document.createElement("label");
            label.className = "ml-3 flex-1 cursor-pointer";
            label.htmlFor = `model-${model.id}`;
            
            const modelName = document.createElement("div");
            modelName.className = "text-sm font-medium text-gray-900";
            modelName.textContent = model.name;
            
            const modelProvider = document.createElement("div");
            modelProvider.className = "text-xs text-gray-500 mt-1";
            modelProvider.textContent = model.provider ? ` - ${model.provider}` : " - Unknown Provider";
            
            label.appendChild(modelName);
            label.appendChild(modelProvider);
            
            modelCard.appendChild(checkbox);
            modelCard.appendChild(label);
            
            // Add click handler to the card
            modelCard.addEventListener('click', (e) => {
              if (e.target !== checkbox) {
                checkbox.checked = !checkbox.checked;
              }
              // Validate requirements when model selection changes
              validateRequirements();
            });
            
            // Add change handler to checkbox for direct clicks
            checkbox.addEventListener('change', validateRequirements);
            
            modelsList.appendChild(modelCard);
          });
        } else {
          modelsList.innerHTML = `
            <div class="flex flex-col items-center justify-center py-8 text-gray-400">
              <i class="fas fa-robot text-3xl mb-3"></i>
              <p class="text-sm font-medium">No models available</p>
              <p class="text-xs">Please check your configuration</p>
            </div>
          `;
        }
        // Validate requirements after models are loaded
        validateRequirements();
      })
      .catch(() => {
        modelsList.innerHTML = `
          <div class="flex flex-col items-center justify-center py-8 text-red-400">
            <i class="fas fa-exclamation-triangle text-3xl mb-3"></i>
            <p class="text-sm font-medium">Failed to load models</p>
            <p class="text-xs">Please try refreshing</p>
          </div>
        `;
        // Validate requirements after error
        validateRequirements();
      });
  }

  if (refreshModelsBtn) {
    refreshModelsBtn.addEventListener("click", loadModels);
  }
  loadModels();

  // Initial validation check
  validateRequirements();

  // Fetch Colab content
  fetchColabBtn.addEventListener("click", function () {
    const link = colabLinkInput.value.trim();
    if (!link) {
      colabStatus.textContent = "Please enter a Google Colab link.";
      colabStatus.className = "ms-2 text-danger";
      return;
    }
    colabStatus.textContent = "Fetching Colab content...";
    colabStatus.className = "ms-2 text-muted";
    colabContentContainer.innerHTML = "";
    reviewResultsSection.innerHTML = "";
    // Extract file_id from Colab link
    let fileId = null;
    try {
      const match = link.match(/\/drive\/([a-zA-Z0-9_-]+)/);
      if (match) fileId = match[1];
    } catch (e) {}
    if (!fileId) {
      colabStatus.textContent = "Invalid Colab link. Please use a link of the form https://colab.research.google.com/drive/<file_id>";
      colabStatus.className = "ms-2 text-danger";
      return;
    }
    fetch("/api/fetch-colab-content/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCSRFToken(),
      },
      body: JSON.stringify({ file_id: fileId }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.success && data.content) {
          colabRawContent = data.content;
          // Use marked.js to render markdown
          colabMarkdown = window.marked ? window.marked.parse(colabRawContent) : colabRawContent;
          colabContentContainer.innerHTML = colabMarkdown;
          colabStatus.textContent = "Colab content loaded.";
          colabStatus.className = "ms-2 text-success";
          // Validate requirements after content is loaded
          validateRequirements();
        } else {
          colabStatus.textContent = data.error || "Failed to fetch Colab content.";
          colabStatus.className = "ms-2 text-danger";
          // Clear content and validate
          colabRawContent = "";
          validateRequirements();
        }
      })
      .catch(() => {
        colabStatus.textContent = "Error fetching Colab content.";
        colabStatus.className = "ms-2 text-danger";
        // Clear content and validate
        colabRawContent = "";
        validateRequirements();
      });
  });

  // Store active polling intervals
  let activePollingIntervals = [];

  // Run Review
  runReviewBtn.addEventListener("click", async function () {
    reviewResultsSection.innerHTML = "";
    const selectedModels = Array.from(
      modelsList.querySelectorAll("input[type=checkbox]:checked")
    );
    const selectedModelIds = selectedModels.map((cb) => cb.value);

    if (!colabRawContent) {
      alert("Please fetch Colab content first.");
      return;
    }
    if (selectedModelIds.length === 0) {
      alert("Please select at least one LLM model.");
      return;
    }

    runReviewBtn.disabled = true;
    runReviewBtn.textContent = "Submitting jobs...";

    // Clear any existing polling intervals
    activePollingIntervals.forEach(interval => clearInterval(interval));
    activePollingIntervals = [];

    try {
      // Submit jobs for each selected model
      const jobPromises = selectedModelIds.map(async (modelId) => {
        const modelCheckbox = document.querySelector(`input[value="${modelId}"]`);
        const modelName = modelCheckbox ? modelCheckbox.parentElement.textContent.trim() : 'Unknown Model';
        
        // Create placeholder for this model
        const placeholder = document.createElement('div');
        placeholder.id = `review-result-${modelId}`;
        placeholder.className = "bg-white p-4 rounded-2xl shadow-lg border border-gray-100 overflow-hidden";
        placeholder.innerHTML = `
          <div class="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-blue-50 to-indigo-50">
            <div class="flex items-center justify-between">
              <div class="flex items-center">
                <div class="p-2 bg-blue-100 rounded-lg mr-3">
                  <i class="fas fa-robot text-blue-600"></i>
                </div>
                <div>
                  <h3 class="text-lg font-semibold text-gray-800">${modelName}</h3>
                  <p class="text-sm text-gray-600">AI Analysis in Progress</p>
                </div>
              </div>
              <div class="flex items-center space-x-2">
                <div class="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
                <span class="text-sm text-blue-600 font-medium">Submitting...</span>
              </div>
            </div>
          </div>
          <div class="p-6">
            <div class="flex items-center justify-center py-8">
              <div class="text-center">
                <div class="animate-pulse">
                  <div class="h-4 bg-gray-200 rounded w-48 mb-2"></div>
                  <div class="h-4 bg-gray-200 rounded w-32"></div>
                </div>
              </div>
            </div>
          </div>
        `;
        reviewResultsSection.appendChild(placeholder);

        // Get additional context and temperature
        const additionalContext = additionalContextTextarea.value.trim();
        const temperature = parseFloat(temperatureSlider.value);
        
        // Submit job to new API
        const response = await fetch('/api/llm/jobs/submit/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
          },
          body: JSON.stringify({
            job_type: 'review_colab',
            model_id: modelId,
            input_data: {
              colab_content: colabRawContent,
              additional_context: additionalContext || null,
              temperature: temperature
            },
            question_id: window.QUESTION_ID || null
          })
        });

        const result = await response.json();
        
        if (result.success) {
          // Update placeholder to show polling status
          const statusSpan = placeholder.querySelector('.text-sm.text-blue-600.font-medium');
          if (statusSpan) {
            statusSpan.textContent = `Processing... (${result.job_id.substring(0, 8)}...)`;
          }
          
          // Start polling for this job
          startPollingForReviewJob(result.job_id, modelId, modelName, placeholder);
          
          return { success: true, modelId, jobId: result.job_id };
        } else {
          // Show error in placeholder
          placeholder.innerHTML = `
            <div class="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-red-50 to-pink-50">
              <div class="flex items-center">
                <div class="p-2 bg-red-100 rounded-lg mr-3">
                  <i class="fas fa-exclamation-triangle text-red-600"></i>
                </div>
                <div>
                  <h3 class="text-lg font-semibold text-gray-800">${modelName}</h3>
                  <p class="text-sm text-red-600">Submission Failed</p>
                </div>
              </div>
            </div>
            <div class="p-6">
              <div class="bg-red-50 border border-red-200 rounded-xl p-4">
                <div class="flex items-center">
                  <i class="fas fa-exclamation-circle text-red-500 mr-2"></i>
                  <span class="text-red-700 font-medium">Error:</span>
                  <span class="text-red-600 ml-2">${result.error}</span>
                </div>
              </div>
            </div>
          `;
          return { success: false, modelId, error: result.error };
        }
      });

      const jobResults = await Promise.all(jobPromises);
      const successfulJobs = jobResults.filter(r => r.success);
      const failedJobs = jobResults.filter(r => !r.success);

      if (successfulJobs.length > 0) {
        runReviewBtn.textContent = `Processing ${successfulJobs.length} job(s)...`;
        if (failedJobs.length > 0) {
          console.warn(`${failedJobs.length} job(s) failed to submit`);
        }
      } else {
        runReviewBtn.textContent = "Run Review";
        runReviewBtn.disabled = false;
        alert("All jobs failed to submit. Please try again.");
      }

    } catch (error) {
      console.error('Error submitting review jobs:', error);
      runReviewBtn.textContent = "Run Review";
      runReviewBtn.disabled = false;
      reviewResultsSection.innerHTML = `<div class="text-red-500">Error: ${error.message}</div>`;
    }
  });

  function startPollingForReviewJob(jobId, modelId, modelName, placeholder) {
    const pollInterval = setInterval(async () => {
      try {
        const response = await fetch(`/api/llm/jobs/${jobId}/status/`);
        const statusData = await response.json();
        
        if (statusData.success && statusData.is_complete) {
          // Job is complete, clear the interval
          clearInterval(pollInterval);
          activePollingIntervals = activePollingIntervals.filter(i => i !== pollInterval);
          
          if (statusData.status === 'completed') {
            // Show successful result
            const result = statusData.result_data;
            placeholder.innerHTML = `
              <div class="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-green-50 to-emerald-50">
                <div class="flex items-center justify-between">
                  <div class="flex items-center">
                    <div class="p-2 bg-green-100 rounded-lg mr-3">
                      <i class="fas fa-check-circle text-green-600"></i>
                    </div>
                    <div>
                      <h3 class="text-lg font-semibold text-gray-800">${modelName}</h3>
                      <p class="text-sm text-gray-600">Analysis Complete</p>
                    </div>
                  </div>
                  <div class="flex items-center space-x-2">
                    <span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
                      <i class="fas fa-clock mr-1"></i>
                      ${statusData.processing_time ? `${statusData.processing_time.toFixed(1)}s` : 'Completed'}
                    </span>
                  </div>
                </div>
              </div>
              
              <div class="p-6">
                <div class="space-y-6">
                  
                  <!-- Grammar Analysis -->
                  <div class="bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl p-5 border border-blue-100">
                    <div class="flex items-center mb-3">
                      <div class="p-2 bg-blue-100 rounded-lg mr-3">
                        <i class="fas fa-spell-check text-blue-600"></i>
                      </div>
                      <h4 class="text-lg font-semibold text-gray-800">Grammar Analysis</h4>
                    </div>
                    <div class="prose prose-sm max-w-none text-gray-700 max-h-64 overflow-y-auto">
                      ${window.marked && result.grammar ? window.marked.parse(result.grammar) : (result.grammar || "No grammar analysis available")}
                    </div>
                  </div>
                  
                  <!-- Plagiarism Check -->
                  <div class="bg-gradient-to-br from-orange-50 to-red-50 rounded-xl p-5 border border-orange-100">
                    <div class="flex items-center mb-3">
                      <div class="p-2 bg-orange-100 rounded-lg mr-3">
                        <i class="fas fa-search text-orange-600"></i>
                      </div>
                      <h4 class="text-lg font-semibold text-gray-800">Plagiarism Check</h4>
                    </div>
                    <div class="mb-3">
                      <div class="flex items-center justify-between mb-2">
                        <span class="text-sm font-medium text-gray-600">Similarity Score</span>
                        <span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-bold ${
                          result.plagiarism_score > 50 ? 'bg-red-100 text-red-800' : 
                          result.plagiarism_score > 25 ? 'bg-yellow-100 text-yellow-800' : 
                          'bg-green-100 text-green-800'
                        }">
                          ${result.plagiarism_score != null ? result.plagiarism_score + "%" : "N/A"}
                        </span>
                      </div>
                      <div class="w-full bg-gray-200 rounded-full h-2">
                        <div class="h-2 rounded-full ${
                          result.plagiarism_score > 50 ? 'bg-red-500' : 
                          result.plagiarism_score > 25 ? 'bg-yellow-500' : 
                          'bg-green-500'
                        }" style="width: ${result.plagiarism_score || 0}%"></div>
                      </div>
                    </div>
                    ${result.plagiarism_result ? `
                      <div class="prose prose-xs max-w-none text-gray-600 max-h-48 overflow-y-auto">
                        ${window.marked ? window.marked.parse(result.plagiarism_result) : result.plagiarism_result}
                      </div>
                    ` : ''}
                  </div>
                  
                  ${result.improvements && result.improvements.trim() && result.improvements.trim().toLowerCase() !== "n/a" ? `
                  <!-- Improvements -->
                  <div class="bg-gradient-to-br from-purple-50 to-pink-50 rounded-xl p-5 border border-purple-100">
                    <div class="flex items-center mb-3">
                      <div class="p-2 bg-purple-100 rounded-lg mr-3">
                        <i class="fas fa-lightbulb text-purple-600"></i>
                      </div>
                      <h4 class="text-lg font-semibold text-gray-800">Suggested Improvements</h4>
                    </div>
                    <div class="prose prose-sm max-w-none text-gray-700 max-h-64 overflow-y-auto">
                      ${window.marked ? window.marked.parse(result.improvements) : result.improvements}
                    </div>
                  </div>
                  ` : ''}
                  
                  <!-- Code Quality Summary -->
                  <div class="bg-gradient-to-br from-green-50 to-teal-50 rounded-xl p-5 border border-green-100">
                    <div class="flex items-center mb-3">
                      <div class="p-2 bg-green-100 rounded-lg mr-3">
                        <i class="fas fa-code text-green-600"></i>
                      </div>
                      <h4 class="text-lg font-semibold text-gray-800">Quality Summary</h4>
                    </div>
                    <div class="prose prose-sm max-w-none text-gray-700 max-h-64 overflow-y-auto">
                      ${window.marked && result.code_quality ? window.marked.parse(result.code_quality) : (result.code_quality || "No quality summary available")}
                    </div>
                  </div>
                  
                </div>
              </div>
            `;
            
          } else if (statusData.status === 'failed') {
            // Show error result
            placeholder.innerHTML = `
              <h5 class="font-bold text-lg">${modelName}</h5>
              <div class="text-red-500">Job failed: ${statusData.error_message || 'Unknown error'}</div>
            `;
          }
          
          // Check if all jobs are complete
          checkAllReviewJobsComplete();
          
        } else if (statusData.success) {
          // Job is still processing, update status
          const statusText = statusData.status === 'processing' ? 'Processing...' : 'In queue...';
          const statusElement = placeholder.querySelector('.text-sm.text-blue-600.font-medium');
          if (statusElement) {
            statusElement.innerHTML = `
              <i class="fas fa-spinner fa-spin mr-1"></i>
              ${statusText} (${statusData.processing_time ? `${statusData.processing_time.toFixed(1)}s` : 'Job ID: ' + jobId.substring(0, 8) + '...'})
            `;
          }
        } else {
          // Error getting status
          clearInterval(pollInterval);
          activePollingIntervals = activePollingIntervals.filter(i => i !== pollInterval);
          if (placeholder && placeholder.parentNode) {
            placeholder.innerHTML = `
              <div class="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-red-50 to-pink-50">
                <div class="flex items-center">
                  <div class="p-2 bg-red-100 rounded-lg mr-3">
                    <i class="fas fa-exclamation-triangle text-red-600"></i>
                  </div>
                  <div>
                    <h3 class="text-lg font-semibold text-gray-800">${modelName}</h3>
                    <p class="text-sm text-red-600">Status Check Failed</p>
                  </div>
                </div>
              </div>
              <div class="p-6">
                <div class="bg-red-50 border border-red-200 rounded-xl p-4">
                  <div class="flex items-center">
                    <i class="fas fa-exclamation-circle text-red-500 mr-2"></i>
                    <span class="text-red-700 font-medium">Error:</span>
                    <span class="text-red-600 ml-2">${statusData.error || 'Unknown error checking job status'}</span>
                  </div>
                </div>
              </div>
            `;
          }
          checkAllReviewJobsComplete();
        }
        
      } catch (error) {
        console.error('Polling error:', error);
        clearInterval(pollInterval);
        activePollingIntervals = activePollingIntervals.filter(i => i !== pollInterval);
        if (placeholder && placeholder.parentNode) {
          placeholder.innerHTML = `
            <div class="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-red-50 to-pink-50">
              <div class="flex items-center">
                <div class="p-2 bg-red-100 rounded-lg mr-3">
                  <i class="fas fa-exclamation-triangle text-red-600"></i>
                </div>
                <div>
                  <h3 class="text-lg font-semibold text-gray-800">${modelName}</h3>
                  <p class="text-sm text-red-600">Polling Error</p>
                </div>
              </div>
            </div>
            <div class="p-6">
              <div class="bg-red-50 border border-red-200 rounded-xl p-4">
                <div class="flex items-center">
                  <i class="fas fa-exclamation-circle text-red-500 mr-2"></i>
                  <span class="text-red-700 font-medium">Error:</span>
                  <span class="text-red-600 ml-2">${error.message || 'Unknown polling error'}</span>
                </div>
              </div>
            </div>
          `;
        }
        checkAllReviewJobsComplete();
      }
    }, 2000); // Poll every 2 seconds
    
    activePollingIntervals.push(pollInterval);
  }

  function checkAllReviewJobsComplete() {
    const allPlaceholders = reviewResultsSection.querySelectorAll('[id^="review-result-"]');
    const stillProcessing = Array.from(allPlaceholders).filter(p => p.querySelector('.fa-spinner'));
    
    if (stillProcessing.length === 0) {
      runReviewBtn.disabled = false;
      runReviewBtn.textContent = "Run Review";
    } else {
      // Update the count to show remaining jobs
      runReviewBtn.textContent = `Processing ${stillProcessing.length} job(s)...`;
    }
  }

  // Expose question_id to JS (for API)
  const questionIdElement = document.querySelector('.text-sm.font-bold.text-blue-600');
  window.QUESTION_ID = questionIdElement ? questionIdElement.textContent.trim() : null;

  console.log("Review page loaded with new polling-based API", { questionId: window.QUESTION_ID });
});
