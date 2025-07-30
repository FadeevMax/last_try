import subprocess
import sys

def handler(request):
    # Start Streamlit server
    subprocess.Popen([
        sys.executable, "-m", "streamlit", "run", 
        "app.py",  # Your main file name
        "--server.port", "8501",
        "--server.address", "0.0.0.0"
    ])
    
    return {
        'statusCode': 200,
        'headers': {
            'Location': f'http://0.0.0.0:8501'
        }
    }
