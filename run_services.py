import subprocess
import sys
import os
import signal
import time

def kill_existing_processes():
    """Kill any existing processes that might be using our ports."""
    print("Checking for existing processes...")
    
    # Check for processes on port 8000
    try:
        result = subprocess.run(['lsof', '-i', ':8000'], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            print("Found processes using port 8000, attempting to terminate...")
            lines = result.stdout.strip().split('\n')[1:]  # Skip header
            pids = []
            for line in lines:
                parts = line.split()
                if len(parts) > 1:
                    try:
                        pid = int(parts[1])
                        pids.append(pid)
                    except ValueError:
                        continue
            
            for pid in set(pids):  # Remove duplicates
                try:
                    print(f"Terminating process {pid}...")
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(1)  # Give it time to terminate gracefully
                except ProcessLookupError:
                    pass  # Process already terminated
                except PermissionError:
                    print(f"Permission denied to terminate process {pid}")
    except FileNotFoundError:
        print("lsof command not found, skipping port check")
    except Exception as e:
        print(f"Error checking for existing processes: {e}")

def run_command(command, name):
    """Runs a command in a new process and returns the process object."""
    print(f"Starting {name}...")
    try:
        return subprocess.Popen(command, shell=True, stdout=sys.stdout, stderr=sys.stderr)
    except Exception as e:
        print(f"Error starting {name}: {e}")
        return None

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
            "gunicorn": f"gunicorn coreproject.wsgi:application --bind 127.0.0.1:8000",
            "sync_daemon": f"{venv_python} run_sync_daemon.py",
            "llm_jobs": f"{venv_python} manage.py process_llm_jobs"
        }
    else:
        # Production mode - only run background services (gunicorn handled by deploy.sh)
        commands = {
            "sync_daemon": f"{venv_python} run_sync_daemon.py",
            "llm_jobs": f"{venv_python} manage.py process_llm_jobs"
        }
    
    # Clean up any existing processes first
    kill_existing_processes()
    
    processes = {}
    try:
        print(f"Starting services for polling-based architecture in {args.mode} mode...")
        for name, cmd in commands.items():
            process = run_command(cmd, name)
            if process:
                processes[name] = process
            else:
                print(f"Failed to start {name}")
        
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
