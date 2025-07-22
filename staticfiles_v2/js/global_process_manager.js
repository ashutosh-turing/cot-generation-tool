/**
 * Global Process Manager
 * Manages the state of running analysis processes across different pages
 * and ensures analysis buttons are disabled when any process is running.
 */

window.GlobalProcessManager = (function() {
    // Store running processes
    let runningProcesses = new Set();
    
    // Store callbacks for when process state changes
    let stateChangeCallbacks = [];
    
    // Process types
    const PROCESS_TYPES = {
        TRAINER_ANALYSIS: 'trainer_question_analysis',
        REVIEW_ANALYSIS: 'review_analysis', 
        MODAL_ANALYSIS: 'modal_analysis'
    };
    
    /**
     * Add a process as running
     * @param {string} processType - Type of process (use PROCESS_TYPES constants)
     * @param {string} processId - Unique identifier for this specific process instance
     */
    function addRunningProcess(processType, processId) {
        const fullProcessId = `${processType}_${processId}`;
        runningProcesses.add(fullProcessId);
        console.log(`[GlobalProcessManager] Added running process: ${fullProcessId}`);
        console.log(`[GlobalProcessManager] Total running processes: ${runningProcesses.size}`);
        notifyStateChange();
    }
    
    /**
     * Remove a process from running state
     * @param {string} processType - Type of process
     * @param {string} processId - Unique identifier for this specific process instance
     */
    function removeRunningProcess(processType, processId) {
        const fullProcessId = `${processType}_${processId}`;
        runningProcesses.delete(fullProcessId);
        console.log(`[GlobalProcessManager] Removed running process: ${fullProcessId}`);
        console.log(`[GlobalProcessManager] Total running processes: ${runningProcesses.size}`);
        notifyStateChange();
    }
    
    /**
     * Check if any processes are currently running
     * @returns {boolean}
     */
    function hasRunningProcesses() {
        return runningProcesses.size > 0;
    }
    
    /**
     * Get all currently running processes
     * @returns {Array<string>}
     */
    function getRunningProcesses() {
        return Array.from(runningProcesses);
    }
    
    /**
     * Check if a specific type of process is running
     * @param {string} processType - Type of process to check
     * @returns {boolean}
     */
    function isProcessTypeRunning(processType) {
        for (let process of runningProcesses) {
            if (process.startsWith(processType)) {
                return true;
            }
        }
        return false;
    }
    
    /**
     * Register a callback to be called when process state changes
     * @param {Function} callback - Function to call when state changes
     */
    function onStateChange(callback) {
        if (typeof callback === 'function') {
            stateChangeCallbacks.push(callback);
        }
    }
    
    /**
     * Unregister a state change callback
     * @param {Function} callback - Function to remove from callbacks
     */
    function offStateChange(callback) {
        const index = stateChangeCallbacks.indexOf(callback);
        if (index > -1) {
            stateChangeCallbacks.splice(index, 1);
        }
    }
    
    /**
     * Notify all registered callbacks about state change
     */
    function notifyStateChange() {
        const isRunning = hasRunningProcesses();
        const runningList = getRunningProcesses();
        
        stateChangeCallbacks.forEach(callback => {
            try {
                callback(isRunning, runningList);
            } catch (error) {
                console.error('[GlobalProcessManager] Error in state change callback:', error);
            }
        });
    }
    
    /**
     * Update analysis buttons based on current state
     * This function finds common analysis button selectors and updates them
     */
    function updateAnalysisButtons() {
        const isRunning = hasRunningProcesses();
        const runningList = getRunningProcesses();
        
        // Common button selectors used across different pages
        const buttonSelectors = [
            '#run-analysis',           // trainer_question_analysis.html and modal_playground.html
            '#run-review-btn'          // review.html
        ];
        
        buttonSelectors.forEach(selector => {
            const button = document.querySelector(selector);
            if (button) {
                const originalText = button.getAttribute('data-original-text') || button.textContent.trim();
                
                // Store original text if not already stored
                if (!button.getAttribute('data-original-text')) {
                    button.setAttribute('data-original-text', originalText);
                }
                
                if (isRunning) {
                    button.disabled = true;
                    button.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Analysis Running...';
                    button.title = `Analysis is currently running: ${runningList.join(', ')}`;
                } else {
                    button.disabled = false;
                    button.innerHTML = `<i class="fas fa-play mr-2"></i>${originalText.replace(/^.*?(?:Run|Start)\s*/i, 'Run ')}`;
                    button.title = '';
                }
            }
        });
    }
    
    // Register the default button updater
    onStateChange(updateAnalysisButtons);
    
    // Public API
    return {
        PROCESS_TYPES,
        addRunningProcess,
        removeRunningProcess,
        hasRunningProcesses,
        getRunningProcesses,
        isProcessTypeRunning,
        onStateChange,
        offStateChange,
        updateAnalysisButtons
    };
})();

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('[GlobalProcessManager] Initialized');
    // Initial button state update
    window.GlobalProcessManager.updateAnalysisButtons();
});
