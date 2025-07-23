/**
 * Privacy-First Activity Tracker
 * Tracks user engagement time for personal productivity insights only.
 * No detailed monitoring - just focus time and basic interaction metrics.
 */

class ActivityTracker {
    constructor() {
        this.sessionId = null;
        this.activityType = null;
        this.startTime = null;
        this.lastActivity = Date.now();
        this.focusTime = 0;
        this.interactions = 0;
        this.isActive = false;
        this.idleThreshold = 5 * 60 * 1000; // 5 minutes idle threshold
        this.syncInterval = 30 * 1000; // Sync every 30 seconds
        this.syncTimer = null;
        this.idleTimer = null;
        
        // Privacy settings - user can disable tracking
        this.trackingEnabled = this.getTrackingPreference();
        
        if (this.trackingEnabled) {
            this.init();
        }
    }
    
    init() {
        // Detect activity type based on current page
        this.detectActivityType();
        
        if (this.activityType) {
            this.startSession();
            this.setupEventListeners();
            this.startSyncTimer();
        }
    }
    
    detectActivityType() {
        const path = window.location.pathname;
        
        if (path.includes('/trainer-question-analysis/')) {
            this.activityType = 'trainer_analysis';
        } else if (path.includes('/review/')) {
            this.activityType = 'review_task';
        } else if (path.includes('/modal-playground/')) {
            this.activityType = 'modal_playground';
        } else if (path.includes('/dashboard/')) {
            this.activityType = 'dashboard_view';
        }
    }
    
    startSession() {
        this.sessionId = this.generateSessionId();
        this.startTime = Date.now();
        this.lastActivity = Date.now();
        this.isActive = true;
        
        // Send session start to server
        this.sendSessionStart();
    }
    
    setupEventListeners() {
        // Track user interactions (privacy-friendly)
        const events = ['click', 'scroll', 'keydown', 'mousemove'];
        
        events.forEach(event => {
            document.addEventListener(event, () => this.recordActivity(), { passive: true });
        });
        
        // Track page focus/blur for accurate time measurement
        window.addEventListener('focus', () => this.handleFocus());
        window.addEventListener('blur', () => this.handleBlur());
        
        // Track page unload to end session
        window.addEventListener('beforeunload', () => this.endSession());
        
        // Track visibility changes (tab switching)
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.handleBlur();
            } else {
                this.handleFocus();
            }
        });
    }
    
    recordActivity() {
        if (!this.isActive) return;
        
        const now = Date.now();
        this.lastActivity = now;
        this.interactions++;
        
        // Reset idle timer
        this.resetIdleTimer();
    }
    
    handleFocus() {
        if (!this.isActive) {
            // Resume session if it was paused
            this.isActive = true;
            this.lastActivity = Date.now();
        }
        this.resetIdleTimer();
    }
    
    handleBlur() {
        // Don't immediately pause - user might be switching between windows
        // Let the idle timer handle it
    }
    
    resetIdleTimer() {
        if (this.idleTimer) {
            clearTimeout(this.idleTimer);
        }
        
        this.idleTimer = setTimeout(() => {
            this.handleIdle();
        }, this.idleThreshold);
    }
    
    handleIdle() {
        // User has been idle - pause focus time tracking
        this.isActive = false;
    }
    
    calculateFocusTime() {
        if (!this.startTime) return 0;
        
        const now = Date.now();
        const totalTime = now - this.startTime;
        
        // Estimate focus time by removing idle periods
        // This is a simple heuristic - more sophisticated tracking could be added
        const idleTime = Math.max(0, now - this.lastActivity - this.idleThreshold);
        const focusTime = Math.max(0, totalTime - idleTime);
        
        return Math.floor(focusTime / 1000 / 60); // Convert to minutes
    }
    
    startSyncTimer() {
        this.syncTimer = setInterval(() => {
            this.syncSession();
        }, this.syncInterval);
    }
    
    syncSession() {
        if (!this.sessionId || !this.trackingEnabled) return;
        
        const focusTime = this.calculateFocusTime();
        
        // Only sync if there's meaningful data
        if (focusTime > 0 || this.interactions > 0) {
            this.sendSessionUpdate({
                session_id: this.sessionId,
                focus_time_minutes: focusTime,
                interactions: this.interactions,
                activity_type: this.activityType,
                is_active: this.isActive
            });
        }
    }
    
    endSession() {
        if (!this.sessionId) return;
        
        // Clear timers
        if (this.syncTimer) clearInterval(this.syncTimer);
        if (this.idleTimer) clearTimeout(this.idleTimer);
        
        // Final sync
        const focusTime = this.calculateFocusTime();
        
        this.sendSessionEnd({
            session_id: this.sessionId,
            focus_time_minutes: focusTime,
            interactions: this.interactions,
            activity_type: this.activityType
        });
        
        this.isActive = false;
    }
    
    // Server communication methods
    sendSessionStart() {
        this.sendToServer('/api/activity/start/', {
            activity_type: this.activityType,
            session_id: this.sessionId
        });
    }
    
    sendSessionUpdate(data) {
        this.sendToServer('/api/activity/update/', data);
    }
    
    sendSessionEnd(data) {
        this.sendToServer('/api/activity/end/', data);
    }
    
    sendToServer(url, data) {
        // Use sendBeacon for reliability, especially on page unload
        if (navigator.sendBeacon) {
            const formData = new FormData();
            formData.append('data', JSON.stringify(data));
            formData.append('csrfmiddlewaretoken', this.getCSRFToken());
            navigator.sendBeacon(url, formData);
        } else {
            // Fallback to fetch for older browsers
            fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(data),
                keepalive: true
            }).catch(error => {
                // Silently handle errors - this is background tracking
                console.debug('Activity tracking error:', error);
            });
        }
    }
    
    // Utility methods
    generateSessionId() {
        return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }
    
    getCSRFToken() {
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'csrftoken') {
                return value;
            }
        }
        return '';
    }
    
    getTrackingPreference() {
        // Check if user has disabled tracking
        const preference = localStorage.getItem('activity_tracking_enabled');
        return preference !== 'false'; // Default to enabled
    }
    
    // Public methods for user control
    enableTracking() {
        localStorage.setItem('activity_tracking_enabled', 'true');
        this.trackingEnabled = true;
        if (!this.isActive && this.activityType) {
            this.init();
        }
    }
    
    disableTracking() {
        localStorage.setItem('activity_tracking_enabled', 'false');
        this.trackingEnabled = false;
        this.endSession();
    }
    
    getTrackingStatus() {
        return {
            enabled: this.trackingEnabled,
            sessionActive: this.isActive,
            activityType: this.activityType,
            focusTime: this.calculateFocusTime(),
            interactions: this.interactions
        };
    }
}

// Initialize activity tracker when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // Only initialize on relevant pages
    const relevantPages = [
        '/trainer-question-analysis/',
        '/review/',
        '/modal-playground/',
        '/dashboard/'
    ];
    
    const currentPath = window.location.pathname;
    const isRelevantPage = relevantPages.some(page => currentPath.includes(page));
    
    if (isRelevantPage) {
        window.activityTracker = new ActivityTracker();
    }
});

// Expose tracker for debugging and user control
window.ActivityTracker = ActivityTracker;
