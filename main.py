import os
import sys
import importlib.util

# Path to Back End/main.py
backend_main_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Back End", "main.py")
backend_dir = os.path.dirname(backend_main_path)

if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Load module from Back End/main.py without module name collision
spec = importlib.util.spec_from_file_location("backend_main", backend_main_path)
backend_module = importlib.util.module_from_spec(spec)
sys.modules["backend_main"] = backend_module
spec.loader.exec_module(backend_module)

# Expose app and load_synthetic_emails
app = backend_module.app
load_synthetic_emails = getattr(backend_module, "load_synthetic_emails", None)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
