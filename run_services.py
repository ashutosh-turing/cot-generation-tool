import subprocess
import sys
import os

def run_command(command, name):
    """Runs a command in a new process and returns the process object."""
    print(f"Starting {name}...")
    return subprocess.Popen(command, shell=True, stdout=sys.stdout, stderr=sys.stderr)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Run services for the evaluation system')
    parser.add_argument('--mode', choices=['dev', 'production'], default='dev',
                       help='Mode to run services in (dev or production)')
    args = parser.parse_args()
    
    # Get the Python executable from the virtual environment
    venv_python = os.path.join(os.path.dirname(__file__), 'bin', 'python')
    
    if args.mode == 'dev':
        # Development mode - run all services including gunicorn
        commands = {
            "gunicorn": f"{venv_python} -m gunicorn coreproject.wsgi:application --bind 127.0.0.1:8000",
            "sync_daemon": f"{venv_python} run_sync_daemon.py",
            "llm_jobs": f"{venv_python} manage.py process_llm_jobs"
        }
    else:
        # Production mode - only run background services (gunicorn handled by deploy.sh)
        commands = {
            "sync_daemon": f"{venv_python} run_sync_daemon.py",
            "llm_jobs": f"{venv_python} manage.py process_llm_jobs"
        }
    
    processes = {}
    try:
        print(f"Starting services for polling-based architecture in {args.mode} mode...")
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
