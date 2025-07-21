import subprocess
import sys
import os

def run_command(command, name):
    """Runs a command in a new process and returns the process object."""
    print(f"Starting {name}...")
    return subprocess.Popen(command, shell=True, stdout=sys.stdout, stderr=sys.stderr)

def main():
    # Ensure the virtual environment is activated
    venv_path = os.path.join(os.path.dirname(__file__), 'bin', 'activate')
    
    # Commands to run - Updated for polling-based architecture
    commands = {
        "gunicorn": f"source {venv_path} && gunicorn coreproject.wsgi:application --bind 127.0.0.1:8000",
        "sync_daemon": f"source {venv_path} && python run_sync_daemon.py",
        "llm_jobs": f"source {venv_path} && python manage.py process_llm_jobs"
    }
    
    processes = {}
    try:
        print("Starting services for polling-based architecture...")
        for name, cmd in commands.items():
            processes[name] = run_command(cmd, name)
        
        print("All services started. Press Ctrl+C to stop all services.")
        
        # Wait for all processes to complete
        for name, p in processes.items():
            p.wait()
            
    except KeyboardInterrupt:
        print("\nShutting down services...")
        for name, p in processes.items():
            print(f"Terminating {name}...")
            p.terminate()
        print("All services stopped.")

if __name__ == "__main__":
    main()
