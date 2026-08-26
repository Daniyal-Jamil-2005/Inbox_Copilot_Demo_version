import os
import sys

# Ensure parent directory is in sys.path
dir_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if dir_path not in sys.path:
    sys.path.insert(0, dir_path)

from main import app
