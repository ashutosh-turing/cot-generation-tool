import os
import sys
import time
import threading
import signal
import django
from datetime import timedelta
from django.utils import timezone
from django.db import connection
import logging

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "coreproject.settings")
django.setup()

from eval.models import TaskSyncConfig
from eval.utils.sheets import sync_trainer_tasks

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(threadName)s] - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('sync_daemon.log')
    ]
)
logger = logging.getLogger('SyncDaemon')

class ConfigSyncWorker(threading.Thread):
    """
    Individual worker thread for each sync configuration.
    Handles timing and execution of sync operations for a specific config.
    """
    
    def __init__(self, config_id, shutdown_event):
        super().__init__(name=f"SyncWorker-{config_id}")
        self.config_id = config_id
        self.shutdown_event = shutdown_event
        self.daemon = True
        self._last_config_check = None
        
    def run(self):
        """Main worker loop for this config"""
        logger.info(f"Started sync worker for config {self.config_id}")
        
        while not self.shutdown_event.is_set():
            try:
                # Get fresh config from database
                config = self._get_config()
                if not config:
                    logger.warning(f"Config {self.config_id} not found or inactive, stopping worker")
                    break
                
                # Check if sync is needed
                if self._should_sync(config):
                    self._perform_sync(config)
                
                # Sleep for a short interval before checking again
                # Use smaller intervals for configs with shorter sync times
                sleep_interval = min(60, config.sync_interval_minutes * 60 / 10)
                self.shutdown_event.wait(sleep_interval)
                
            except Exception as e:
                logger.error(f"Error in sync worker for config {self.config_id}: {e}", exc_info=True)
                # Wait before retrying to avoid rapid error loops
                self.shutdown_event.wait(60)
        
        logger.info(f"Sync worker for config {self.config_id} stopped")
    
    def _get_config(self):
        """Get fresh config from database with connection management"""
        try:
            # Ensure we have a fresh database connection
            connection.ensure_connection()
            return TaskSyncConfig.objects.filter(id=self.config_id, is_active=True).first()
        except Exception as e:
            logger.error(f"Error fetching config {self.config_id}: {e}")
            return None
    
    def _should_sync(self, config):
        """Check if sync is needed based on interval and last sync time"""
        now = timezone.now()
        
        # If never synced, sync immediately
        if not config.last_synced:
            return True
        
        # Check if enough time has passed
        time_since_sync = now - config.last_synced
        return time_since_sync >= timedelta(minutes=config.sync_interval_minutes)
    
    def _perform_sync(self, config):
        """Perform the actual sync operation"""
        now = timezone.now()
        project_name = config.project.code if config.project else "Unknown"
        
        logger.info(f"Starting sync for config {self.config_id} (Project: {project_name})")
        start_time = time.time()
        
        try:
            status, summary, details, created, updated, deleted = sync_trainer_tasks(
                config,
                selected_project=config.project,
                sync_type="auto",
                synced_by="system"
            )
            
            duration = time.time() - start_time
            logger.info(f"Sync completed for config {self.config_id} (Project: {project_name}) "
                       f"in {duration:.2f}s - Status: {status}, Summary: {summary}")
            
            if details:
                logger.debug(f"Sync details for config {self.config_id}: {details}")
                
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Sync failed for config {self.config_id} (Project: {project_name}) "
                        f"after {duration:.2f}s: {e}", exc_info=True)


class SyncDaemonManager:
    """
    Main daemon manager that oversees all sync workers.
    Handles worker lifecycle, config changes, and graceful shutdown.
    """
    
    def __init__(self):
        self.workers = {}  # config_id -> worker thread
        self.shutdown_event = threading.Event()
        self.config_check_interval = 30  # Check for config changes every 30 seconds
        
    def start(self):
        """Start the sync daemon manager"""
        logger.info("Starting TaskSyncConfig multi-threaded auto-sync daemon...")
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        try:
            self._main_loop()
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        finally:
            self._shutdown()
    
    def _main_loop(self):
        """Main daemon loop that manages worker threads"""
        while not self.shutdown_event.is_set():
            try:
                # Get current active configs
                active_configs = self._get_active_configs()
                current_config_ids = {config.id for config in active_configs}
                
                # Start workers for new configs
                for config in active_configs:
                    if config.id not in self.workers:
                        self._start_worker(config)
                
                # Stop workers for removed/inactive configs
                for config_id in list(self.workers.keys()):
                    if config_id not in current_config_ids:
                        self._stop_worker(config_id)
                
                # Clean up dead workers
                self._cleanup_dead_workers()
                
                # Log status
                self._log_status()
                
                # Wait before next check
                self.shutdown_event.wait(self.config_check_interval)
                
            except Exception as e:
                logger.error(f"Error in main daemon loop: {e}", exc_info=True)
                self.shutdown_event.wait(60)  # Wait before retrying
    
    def _get_active_configs(self):
        """Get all active sync configurations"""
        try:
            connection.ensure_connection()
            return list(TaskSyncConfig.objects.filter(is_active=True))
        except Exception as e:
            logger.error(f"Error fetching active configs: {e}")
            return []
    
    def _start_worker(self, config):
        """Start a new worker thread for a config"""
        project_name = config.project.code if config.project else "Unknown"
        logger.info(f"Starting worker for config {config.id} (Project: {project_name}, "
                   f"Interval: {config.sync_interval_minutes}min)")
        
        worker = ConfigSyncWorker(config.id, self.shutdown_event)
        worker.start()
        self.workers[config.id] = worker
    
    def _stop_worker(self, config_id):
        """Stop a worker thread for a config"""
        if config_id in self.workers:
            logger.info(f"Stopping worker for config {config_id}")
            worker = self.workers[config_id]
            # Worker will stop when shutdown_event is set or config becomes inactive
            del self.workers[config_id]
    
    def _cleanup_dead_workers(self):
        """Remove references to dead worker threads"""
        dead_workers = []
        for config_id, worker in self.workers.items():
            if not worker.is_alive():
                dead_workers.append(config_id)
        
        for config_id in dead_workers:
            logger.warning(f"Cleaning up dead worker for config {config_id}")
            del self.workers[config_id]
    
    def _log_status(self):
        """Log current daemon status"""
        active_workers = len([w for w in self.workers.values() if w.is_alive()])
        logger.info(f"Daemon status: {active_workers} active workers for configs: "
                   f"{list(self.workers.keys())}")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_event.set()
    
    def _shutdown(self):
        """Gracefully shutdown all workers"""
        logger.info("Shutting down sync daemon...")
        
        # Signal all workers to stop
        self.shutdown_event.set()
        
        # Wait for workers to finish (with timeout)
        for config_id, worker in self.workers.items():
            logger.info(f"Waiting for worker {config_id} to finish...")
            worker.join(timeout=30)  # 30 second timeout
            if worker.is_alive():
                logger.warning(f"Worker {config_id} did not stop gracefully")
        
        logger.info("Sync daemon shutdown complete")


def run_sync_loop():
    """
    Main entry point for the sync daemon.
    Creates and starts the daemon manager.
    """
    daemon = SyncDaemonManager()
    daemon.start()


if __name__ == "__main__":
    run_sync_loop()
