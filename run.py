import os
import sys
import subprocess
import venv

def main():
    print("=========================================================")
    print("    LedgerBoard Transaction Ranker Setup & Runner        ")
    print("=========================================================")
    
    # 1. Create Virtual Environment
    venv_dir = os.path.join(os.path.dirname(__file__), ".venv")
    if not os.path.exists(venv_dir):
        print(f"[1/3] Creating virtual environment in: {venv_dir}...")
        try:
            venv.create(venv_dir, with_pip=True)
            print("      Virtual environment created successfully.")
        except Exception as e:
            print(f"Error creating virtual environment: {e}")
            sys.exit(1)
    else:
        print("[1/3] Virtual environment already exists.")
        
    # 2. Get binary paths inside the virtual environment
    if sys.platform == "win32":
        pip_path = os.path.join(venv_dir, "Scripts", "pip.exe")
        python_path = os.path.join(venv_dir, "Scripts", "python.exe")
        uvicorn_path = os.path.join(venv_dir, "Scripts", "uvicorn.exe")
    else:
        pip_path = os.path.join(venv_dir, "bin", "pip")
        python_path = os.path.join(venv_dir, "bin", "python")
        uvicorn_path = os.path.join(venv_dir, "bin", "uvicorn")
        
    # 3. Install packages
    req_file = os.path.join(os.path.dirname(__file__), "requirements.txt")
    if os.path.exists(req_file):
        print("[2/3] Installing dependencies from requirements.txt...")
        try:
            # Upgrade pip first inside virtualenv to avoid warnings
            subprocess.run([pip_path, "install", "--upgrade", "pip"], stdout=subprocess.DEVNULL)
            subprocess.check_call([pip_path, "install", "-r", req_file])
            print("      Dependencies installed successfully.")
        except subprocess.CalledProcessError as e:
            print(f"Error installing dependencies: {e}")
            sys.exit(1)
    else:
        print(f"[ERROR] requirements.txt not found at {req_file}")
        sys.exit(1)
        
    # 4. Start Server
    print("[3/3] Starting FastAPI Uvicorn Server...")
    port = os.environ.get("PORT", "8000")
    print(f"      Running at: http://127.0.0.1:{port}")
    print(f"      Swagger Docs: http://127.0.0.1:{port}/docs")
    print("      Press Ctrl+C to stop the server.")
    print("---------------------------------------------------------")
    
    try:
        subprocess.check_call([uvicorn_path, "main:app", "--host", "127.0.0.1", "--port", port, "--reload"])
    except KeyboardInterrupt:
        print("\n[SYSTEM] Server stopped by user.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Server exited with error: {e}")
    except Exception as e:
        print(f"[ERROR] Failed to launch server: {e}")

if __name__ == "__main__":
    main()
